"""Switch selected hosts to PSK after installing their agent configuration."""
import argparse
import json
import os
from pathlib import Path
from psk_common import ROOT, host_name, rpc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, type=host_name)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    config = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                  if line and not line.startswith("#") and "=" in line)
    session = rpc("user.login", {"username": "Admin", "password": config["ZABBIX_ADMIN_PASSWORD"]})
    try:
        hosts = rpc("host.get", {"output": ["hostid", "host", "tls_connect", "tls_accept"],
                                 "filter": {"host": [args.host]}}, session)
        if len(hosts) != 1:
            raise RuntimeError("Expected exactly one matching host")
        host = hosts[0]
        private = Path(__file__).parent / "private"
        private.mkdir(mode=0o700, exist_ok=True)
        private.chmod(0o700)
        backup = private / (args.host + ".server-before.json")
        if args.rollback:
            previous = json.loads(backup.read_text())
            if previous["hostid"] != host["hostid"]:
                raise RuntimeError("Host ID differs from backup; refusing rollback")
            rpc("host.update", previous, session)
        else:
            if not backup.exists():
                if host["tls_connect"] != "1" or host["tls_accept"] != "1":
                    raise RuntimeError("Existing host encryption found; refusing to overwrite without a backup")
                fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as file:
                    json.dump({k: host[k] for k in ("hostid", "tls_connect", "tls_accept")}, file)
            key = (private / (args.host + ".psk")).read_text().strip()
            rpc("host.update", {"hostid": host["hostid"], "tls_connect": 2, "tls_accept": 2,
                                "tls_psk_identity": "staj-" + args.host, "tls_psk": key}, session)
        print(args.host + (": previous server TLS settings restored" if args.rollback else ": server requires PSK in both directions"))
    finally:
        rpc("user.logout", [], session)


if __name__ == "__main__":
    main()
