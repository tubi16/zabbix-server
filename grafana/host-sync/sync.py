"""Synchronize Zabbix hosts to Grafana v2 dashboards and a dedicated playlist."""
import copy
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

OWNER = "zabbix-host-sync"
ANNOTATION = "host-sync.local/owner"
DIGEST = "host-sync.local/config-hash"
FOLDER_UID = "zabbix-linux-devices"
FOLDER_ANNOTATION = "grafana.app/folder"
LOG = logging.getLogger(OWNER)


class API:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token

    def request(self, method, path="", data=None, missing_ok=False):
        request = Request(self.url + path,
                          data=None if data is None else json.dumps(data).encode(),
                          headers={"Authorization": "Bearer " + self.token,
                                   "Content-Type": "application/json"}, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            # Do not log request bodies, API error bodies, or credentials.
            raise RuntimeError(f"API HTTP {error.code} ({method} {path})") from None

    def rpc(self, method, params):
        result = self.request("POST", data={"jsonrpc": "2.0", "id": 1,
                                           "method": method, "params": params})
        if "error" in result:
            raise RuntimeError(f"Zabbix {method} failed (code {result['error'].get('code')})")
        return result["result"]


def host_uid(hostid):
    # Renames do not create duplicate dashboards.
    return "zbx-host-" + str(int(hostid))


def host_os(host, group):
    """Prefer linked OS templates, then inventory, then explicit OS groups."""
    templates = " ".join(t.get("host", "") + " " + t.get("name", "")
                         for t in host.get("parentTemplates", []))
    inventory = host.get("inventory") or {}
    groups = " ".join(g.get("name", "") for g in host.get("hostgroups", [])) or group
    for evidence in (templates, " ".join(inventory.get(k, "") for k in ("os", "os_full", "os_short")), groups):
        windows = bool(re.search(r"\bwindows\b", evidence, re.I))
        linux = bool(re.search(r"\b(linux|ubuntu|debian|arch|centos|rocky|alma|rhel|fedora|suse)\b", evidence, re.I))
        if windows != linux:
            return "Windows" if windows else "Linux"
        if windows and linux:
            return "Unknown OS"
    if any(t.get("host") in ("Essential Items", "Essential Items Active")
           for t in host.get("parentTemplates", [])):
        return "Linux"
    return "Unknown OS"


def render(template, host, group, datasource):
    dashboard = {"apiVersion": "dashboard.grafana.app/v2", "kind": "Dashboard",
                 "metadata": {"name": host_uid(host["hostid"]),
                              "annotations": {FOLDER_ANNOTATION: FOLDER_UID}},
                 "spec": copy.deepcopy(template["spec"])}
    spec = dashboard["spec"]
    name = host.get("name") or host["host"]
    operating_system = host_os(host, group)
    spec["title"] = f"{operating_system} — {name} [{host['hostid']}]"
    spec["description"] = f"Operating system: {operating_system}. Automatically managed host dashboard."
    spec["tags"] = sorted(set(spec.get("tags", [])) | {OWNER, "os:" + operating_system})
    spec["timeSettings"].update({"from": "now-1h", "to": "now", "autoRefresh": "10s"})

    def rewrite(value):
        if isinstance(value, dict):
            if isinstance(value.get("datasource"), dict):
                value["datasource"]["name"] = datasource
            if operating_system == "Windows" and isinstance(value.get("item"), dict):
                filters = {"Active Download Speed": "/^Active Download Speed:/",
                           "Active Upload Speed": "/^Active Upload Speed:/",
                           "System Time": "System Uptime", "CPU Load": "CPU Utilization",
                           "/^CPU time:/": "/^Process user CPU time rate:/"}
                current = value["item"].get("filter")
                if current in filters:
                    value["item"]["filter"] = filters[current]
            for child in value.values():
                rewrite(child)
        elif isinstance(value, list):
            for child in value:
                rewrite(child)
    rewrite(spec)
    for element in spec.get("elements", {}).values():
        panel = element.get("spec", {})
        if operating_system == "Windows" and panel.get("title") == "CPU Load":
            panel["title"] = "CPU Utilization (%)"
            defaults = panel["vizConfig"]["spec"]["fieldConfig"]["defaults"]
            defaults.update({"unit": "percent", "min": 0, "max": 100})
        if panel.get("title") == "New panel":
            panel["title"] = "Process user CPU time rate" if operating_system == "Windows" else "Process CPU time rate"
    found = set()
    for variable in spec["variables"]:
        config = variable["spec"]
        if config["name"] not in ("Group", "Host"):
            continue
        found.add(config["name"])
        selected = group if config["name"] == "Group" else name
        config["current"] = {"text": selected, "value": selected}
        config["multi"] = False
        config["includeAll"] = False
        config["allowCustomValue"] = False
        # Keep the query scoped to this host, including after page reloads.
        query = config["query"]["spec"]
        query["group"] = "/^" + re.escape(group).replace("/", "\\/") + "$/"
        if config["name"] == "Host":
            query["host"] = "/^" + re.escape(name).replace("/", "\\/") + "$/"
    if found != {"Group", "Host"}:
        raise ValueError("Template must contain Group and Host variables")
    return dashboard


def resource(api_version, kind, name, spec):
    return {"apiVersion": api_version, "kind": kind,
            "metadata": {"name": name}, "spec": spec}


def upsert(api, collection, desired):
    path = collection + "/" + desired["metadata"]["name"]
    current = api.request("GET", path, missing_ok=True)
    folder = desired["metadata"].get("annotations", {}).get(FOLDER_ANNOTATION)
    digest = hashlib.sha256(json.dumps([desired["spec"], folder], sort_keys=True).encode()).hexdigest()
    if current:
        annotations = current["metadata"].get("annotations", {})
        if annotations.get(ANNOTATION) != OWNER:
            raise RuntimeError("Resource UID already belongs to an unmanaged object")
        if annotations.get(DIGEST) == digest:
            return False
        desired["metadata"] = copy.deepcopy(current["metadata"])
    desired["metadata"].setdefault("annotations", {}).update({ANNOTATION: OWNER, DIGEST: digest})
    if folder:
        desired["metadata"]["annotations"][FOLDER_ANNOTATION] = folder
    api.request("PUT" if current else "POST", path if current else collection, desired)
    return True


def sync(zabbix, grafana, template, group, datasource, interval):
    # Validate the data source before creating any dashboards.
    source = grafana.request("GET", "/api/datasources/uid/" + datasource)
    if source.get("type") != "alexanderzobnin-zabbix-datasource":
        raise ValueError("Configured datasource must be a Zabbix datasource")
    group_names = list(dict.fromkeys(g.strip() for g in group.split(",") if g.strip()))
    if not group_names:
        raise ValueError("At least one host group must be configured")
    groups = zabbix.rpc("hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": group_names}})
    if not groups:
        raise RuntimeError("Host group is absent or API user has no access; playlist left unchanged")
    # Grafana can return 403 rather than 404 for an absent folder to Editors.
    folders = grafana.request("GET", "/api/search?type=dash-folder&query=Zabbix%20Linux%20devices")
    folder = next((item for item in folders if item.get("uid") == FOLDER_UID), None)
    if folder is None:
        grafana.request("POST", "/api/folders", {"uid": FOLDER_UID, "title": "Zabbix Linux devices"})
    elif folder.get("title") != "Zabbix Linux devices":
        raise RuntimeError("Managed folder UID belongs to another folder")
    hosts = zabbix.rpc("host.get", {"output": ["hostid", "host", "name"],
                                   "groupids": [g["groupid"] for g in groups],
                                   "selectHostGroups": ["groupid", "name"],
                                   "selectParentTemplates": ["host", "name"],
                                   "selectInventory": ["os", "os_full", "os_short"],
                                   "filter": {"status": "0"}})
    hosts = list({h["hostid"]: h for h in hosts}.values())
    hosts.sort(key=lambda host: ((host.get("name") or host["host"]).casefold(), int(host["hostid"])))
    changed = 0
    for host in hosts:
        memberships = {g["name"] for g in host.get("hostgroups", [])}
        host_group = next((g for g in group_names if g in memberships), group_names[0])
        changed += upsert(grafana, "/apis/dashboard.grafana.app/v2/namespaces/default/dashboards",
                          render(template, host, host_group, datasource))
    # Update only after every dashboard is available. Never delete dashboards.
    playlist = resource("playlist.grafana.app/v1", "Playlist", "zabbix-linux-hosts",
                        {"title": "Zabbix — Devices", "interval": interval,
                         "items": [{"type": "dashboard_by_uid", "value": host_uid(h["hostid"])}
                                   for h in hosts]})
    changed += upsert(grafana, "/apis/playlist.grafana.app/v1/namespaces/default/playlists", playlist)
    LOG.info("Synced %d hosts; %d resources changed", len(hosts), changed)


def read_token(service):
    value = os.getenv(service.upper() + "_SERVICE_TOKEN", "").strip()
    if not value:
        value = Path("/run/secrets/" + service + "_token").read_text().strip()
    if not value:
        raise ValueError("Service token must not be empty")
    if not value.isascii() or any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in value):
        raise ValueError(service.upper() + "_SERVICE_TOKEN must contain only printable ASCII without whitespace; use the generated token value, not its name")
    return value


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    period = max(10, int(os.getenv("SYNC_SECONDS", "60")))
    while True:
        try:
            tokens = [read_token(service) for service in ("zabbix", "grafana")]
            template_path = Path(os.getenv("DASHBOARD_TEMPLATE", "/templates/linux-template.json"))
            template = json.loads(template_path.read_text())
            if template.get("apiVersion") != "dashboard.grafana.app/v2":
                raise ValueError("Expected Grafana v2 dashboard template")
            zabbix = API(os.getenv("ZABBIX_URL", "http://zabbix-web-nginx-mysql:8080/api_jsonrpc.php"), tokens[0])
            grafana = API(os.getenv("GRAFANA_URL", "http://grafana:3000"), tokens[1])
            datasource = os.getenv("GRAFANA_DATASOURCE_UID", "zabbix")
            customer_config = os.getenv("CUSTOMER_CONFIG", "").strip()
            if customer_config:
                from customer_dashboards import load_customers, sync_customers
                sync_customers(sys.modules[__name__], zabbix, grafana, template,
                               load_customers(customer_config), datasource)
            else:
                sync(zabbix, grafana, template,
                     os.getenv("ZABBIX_HOST_GROUPS", os.getenv("ZABBIX_HOST_GROUP", "Linux servers") + ",Windows servers"),
                     datasource, os.getenv("PLAYLIST_INTERVAL", "30s"))
        except Exception as error:
            # Unexpected errors are identified without dumping potentially sensitive bodies.
            if isinstance(error, (RuntimeError, ValueError, FileNotFoundError)):
                LOG.error("Sync failed: %s", error)
            else:
                LOG.error("Sync failed: %s", type(error).__name__)
        time.sleep(period)


if __name__ == "__main__":
    main()
