"""Enroll a Linux host with per-device PSK, agent verification and Zabbix setup."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from psk_common import PRIVATE, ROOT, ensure_key, host_name, read_env, rpc

MANAGED_TAG = {"tag": "tls-provisioner", "value": "staj-psk-v1"}


def write_state(path, state):
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(state, file, indent=2)
    os.replace(temporary, path)


def merged_ids(existing, field, required):
    return [{field: value} for value in sorted({str(item[field]) for item in existing} | {str(required)})]


class Enrollment:
    def __init__(self, args, call=rpc, run=subprocess.run, private=PRIVATE):
        self.args, self.call, self.run, self.private = args, call, run, private
        self.session = None
        self.state = {}
        self.agent_source = args.agent_source.expanduser().resolve()

    def api(self, method, params):
        return self.call(method, params, self.session)

    def command(self, args, **kwargs):
        return self.run(args, cwd=ROOT, check=True, **kwargs)

    def preflight(self):
        if not (self.agent_source / "install.py").is_file():
            raise RuntimeError("Agent source not found; clone the agent repo and pass --agent-source /path/to/repo")
        groups = self.api("hostgroup.get", {"output": ["groupid"], "filter": {"name": [self.args.group]}})
        templates = self.api("template.get", {"output": ["templateid"], "filter": {"host": [self.args.template]}})
        if len(groups) != 1 or len(templates) != 1:
            raise RuntimeError("Group or template missing; import Essential Items and check the group first")
        self.groupid, self.templateid = groups[0]["groupid"], templates[0]["templateid"]
        hosts = self.api("host.get", {"output": ["hostid", "host", "tls_connect", "tls_accept"],
                                      "selectHostGroups": ["groupid"], "selectParentTemplates": ["templateid"],
                                      "selectInterfaces": ["interfaceid", "main", "type", "useip", "ip", "dns", "port"],
                                      "selectTags": ["tag", "value"], "filter": {"host": [self.args.host]}})
        if len(hosts) > 1:
            raise RuntimeError("Ambiguous host name")
        self.existing = hosts[0] if hosts else None
        self.state_path = self.private / (self.args.host + ".enrollment.json")
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
        if self.existing:
            recorded = self.state.get("hostid")
            if recorded and recorded != self.existing["hostid"]:
                raise RuntimeError("Host ID changed; inspect saved enrollment before continuing")
            encrypted = any(str(self.existing[k]) != "1" for k in ("tls_connect", "tls_accept"))
            if encrypted and (not recorded or MANAGED_TAG not in self.existing.get("tags", [])):
                raise RuntimeError("Existing unmanaged host encryption found; refusing implicit PSK rotation")
            interfaces = [i for i in self.existing.get("interfaces", []) if str(i["type"]) == "1" and str(i["main"]) == "1"]
            if len(interfaces) > 1:
                raise RuntimeError("Multiple main agent interfaces; inspect host manually")
        # Confirm container tooling before touching the agent.
        self.command(["docker", "compose", "exec", "-T", "zabbix-server", "sh", "-c", "command -v zabbix_get"],
                     capture_output=True)

    def prepare(self):
        self.key_path = ensure_key(self.args.host, self.private)
        self.key = self.key_path.read_text().strip()
        if not self.state:
            self.state = {"host": self.args.host, "hostid": self.existing["hostid"] if self.existing else None,
                          "phase": "prepared", "original": self.existing}
        write_state(self.state_path, self.state)
        if self.args.ssh:
            self.remote = "staj-zabbix-tls/" + self.args.host
            script = "umask 077; mkdir -p " + shlex.quote(self.remote) + "; chmod 700 " + shlex.quote(self.remote)
            self.command(["ssh", "--", self.args.ssh, script])
            self.command(["scp", "--", str(self.agent_source / "install.py"), str(self.key_path),
                          self.args.ssh + ":" + self.remote + "/"])

    def install(self, strict=False):
        directory = self.remote if self.args.ssh else str(self.agent_source)
        key = directory + "/" + self.args.host + ".psk" if self.args.ssh else str(self.key_path)
        command = ["sudo", "python3", directory + "/install.py", "--host", self.args.host,
                   "--key", key, "--agent", self.args.agent, "--port", str(self.args.port)]
        for server in self.args.server:
            command.extend(["--server", server])
        if strict:
            command.append("--strict")
        if self.args.ssh:
            command = ["ssh", "-t", "--", self.args.ssh, shlex.join(command)]
        self.command(command)

    def probe(self, encrypted=True):
        if encrypted:
            # Key goes only through stdin into a private temporary container file,
            # never command-line arguments, environment variables or logs.
            script = '''set -eu
keyfile=$(mktemp /tmp/staj-psk.XXXXXX)
chmod 600 "$keyfile"
trap 'rm -f "$keyfile"' EXIT HUP INT TERM
cat > "$keyfile"
zabbix_get -s "$1" -p "$2" -k agent.ping -t 5 --tls-connect psk --tls-psk-identity "$3" --tls-psk-file "$keyfile"
'''
            command = ["docker", "compose", "exec", "-T", "zabbix-server", "sh", "-c", script,
                       "probe", self.args.address, str(self.args.port), "staj-" + self.args.host]
            result = self.run(command, cwd=ROOT, input=(self.key + "\n").encode(), capture_output=True, timeout=20)
        else:
            command = ["docker", "compose", "exec", "-T", "zabbix-server", "zabbix_get",
                       "-s", self.args.address, "-p", str(self.args.port), "-k", "agent.ping", "-t", "5",
                       "--tls-connect", "unencrypted"]
            result = self.run(command, cwd=ROOT, capture_output=True, timeout=20)
        successful = result.returncode == 0 and result.stdout.strip() == b"1"
        if encrypted and not successful:
            raise RuntimeError("PSK probe from Zabbix server failed; check agent config, route and Server allowlist")
        if not encrypted and successful:
            raise RuntimeError("Agent still accepts plaintext; enrollment is not complete")

    def register(self):
        groups = merged_ids(self.existing.get("hostgroups", []) if self.existing else [], "groupid", self.groupid)
        templates = merged_ids(self.existing.get("parentTemplates", []) if self.existing else [], "templateid", self.templateid)
        interface = {"type": 1, "main": 1, "useip": 1, "ip": self.args.address, "dns": "", "port": str(self.args.port)}
        data = {"groups": groups, "templates": templates, "tls_connect": 2, "tls_accept": 2,
                "tls_psk_identity": "staj-" + self.args.host, "tls_psk": self.key}
        tags = self.existing.get("tags", []) if self.existing else []
        data["tags"] = [t for t in tags if t["tag"] != MANAGED_TAG["tag"]] + [MANAGED_TAG]
        if self.existing:
            data["hostid"] = self.existing["hostid"]
            main = next((i for i in self.existing.get("interfaces", []) if str(i["type"]) == "1" and str(i["main"]) == "1"), None)
            if main:
                self.api("hostinterface.update", {"interfaceid": main["interfaceid"], **interface})
            else:
                self.api("hostinterface.create", {"hostid": data["hostid"], **interface})
            self.api("host.update", data)
            hostid = data["hostid"]
        else:
            data.update({"host": self.args.host, "name": self.args.host, "interfaces": [interface]})
            hostid = self.api("host.create", data)["hostids"][0]
        self.state.update({"hostid": hostid, "phase": "server-psk"})
        write_state(self.state_path, self.state)

    def execute(self):
        self.preflight()
        self.prepare()
        print("1/4 Preparing agent (sudo may prompt on the target)", flush=True)
        self.install()
        self.probe()
        print("2/4 PSK verified from server; registering host", flush=True)
        self.register()
        self.command(["docker", "compose", "exec", "-T", "zabbix-server", "zabbix_server", "-R", "config_cache_reload"],
                     capture_output=True)
        print("3/4 Disabling plaintext on agent (sudo may prompt again)", flush=True)
        self.install(strict=True)
        self.probe()
        self.probe(encrypted=False)
        self.state["phase"] = "complete"
        write_state(self.state_path, self.state)
        print("4/4 Complete: PSK succeeds; plaintext rejected. Dashboard sync follows its configured group.", flush=True)

    def rollback(self):
        path = self.private / (self.args.host + ".enrollment.json")
        state = json.loads(path.read_text())
        hosts = self.api("host.get", {"output": ["hostid"], "filter": {"host": [self.args.host]}})
        if len(hosts) != 1 or hosts[0]["hostid"] != state.get("hostid"):
            raise RuntimeError("Host ID differs from saved enrollment; refusing rollback")
        if state.get("original"):
            previous = state["original"]
            self.api("host.update", {k: previous[k] for k in ("hostid", "tls_connect", "tls_accept")})
            print("Original server TLS settings restored; agent must be restored from its first backup.")
        else:
            self.api("host.update", {"hostid": state["hostid"], "status": 1})
            print("New host disabled; history, keys and host record preserved.")
        state["phase"] = "rolled-back"
        write_state(path, state)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, type=host_name)
    parser.add_argument("--address", required=True, type=lambda value: str(ipaddress.ip_address(value)))
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--ssh", help="Existing SSH alias or user@host; uses your SSH configuration")
    target.add_argument("--local", action="store_true")
    parser.add_argument("--server", action="append", required=True, help="Allowed server source IP/subnet, repeatable")
    parser.add_argument("--agent", choices=["auto", "classic", "agent2"], default="auto")
    parser.add_argument("--port", type=int, default=10050)
    parser.add_argument("--group", default="Linux servers")
    parser.add_argument("--template", default="Essential Items")
    parser.add_argument("--agent-source", type=Path, default=ROOT.parent / "staj-agent",
                        help="Local clone of the separate agent repo; default ../staj-agent")
    parser.add_argument("--plan", action="store_true", help="Show plan without connecting or changing anything")
    parser.add_argument("--rollback", action="store_true", help="Restore saved server TLS settings or disable a newly created host")
    args = parser.parse_args(argv)
    if args.ssh and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*", args.ssh):
        parser.error("Use a simple SSH alias or user@host, not shell options")
    for server in args.server:
        ipaddress.ip_network(server, strict=False)
    if not 1024 <= args.port <= 32767:
        parser.error("Agent port must be between 1024 and 32767")
    return args


def main():
    args = arguments()
    if args.plan:
        print("Host:", args.host, "agent:", args.address + ":" + str(args.port), "target:", args.ssh or "local")
        print("Generate/reuse unique PSK; install agent TLS; probe; add/update host; reject plaintext.")
        print("Group:", args.group, "template:", args.template, "allowed server sources:", ", ".join(args.server))
        print("Agent source:", args.agent_source.expanduser().resolve())
        return
    if not sys.stdin.isatty():
        raise SystemExit("Run from an interactive terminal for sudo prompts; use --plan for preview")
    config = read_env()
    password = config.get("ZABBIX_ADMIN_PASSWORD", "")
    if not password.strip():
        raise SystemExit("ZABBIX_ADMIN_PASSWORD is empty in .env; run python3 scripts/bootstrap_admin.py first.")
    try:
        session = rpc("user.login", {"username": "Admin", "password": password})
    except RuntimeError:
        raise SystemExit("Zabbix Admin login failed. Check .env password and temporary account lock. For a fresh installation run python3 scripts/bootstrap_admin.py; no agent changes made.") from None
    try:
        PRIVATE.mkdir(mode=0o700, exist_ok=True)
        PRIVATE.chmod(0o700)
        descriptor = os.open(PRIVATE / (args.host + ".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another enrollment is already running for this host") from None
            enrollment = Enrollment(args)
            enrollment.session = session
            if args.rollback:
                enrollment.rollback()
            else:
                enrollment.execute()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("Enrollment incomplete:", str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__, file=sys.stderr)
        print("Progress saved in zabbix/tls/private/. Fix the cause and rerun the same command.", file=sys.stderr)
        print("Agent backups and rollback commands are printed during install; no plaintext fallback is applied automatically.", file=sys.stderr)
        raise SystemExit(1)
    finally:
        try:
            rpc("user.logout", [], session)
        except Exception:
            pass


if __name__ == "__main__":
    main()
