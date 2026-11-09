"""Synchronize Zabbix hosts to Grafana v2 dashboards and a dedicated playlist."""
import copy
import hashlib
import json
import logging
import os
from pathlib import Path
import re
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


def render(template, host, group, datasource):
    dashboard = {"apiVersion": "dashboard.grafana.app/v2", "kind": "Dashboard",
                 "metadata": {"name": host_uid(host["hostid"]),
                              "annotations": {FOLDER_ANNOTATION: FOLDER_UID}},
                 "spec": copy.deepcopy(template["spec"])}
    spec = dashboard["spec"]
    name = host.get("name") or host["host"]
    spec["title"] = f"Linux — {name} [{host['hostid']}]"
    spec["tags"] = sorted(set(spec.get("tags", [])) | {OWNER})
    spec["timeSettings"].update({"from": "now-1h", "to": "now", "autoRefresh": "10s"})

    def rewrite(value):
        if isinstance(value, dict):
            if isinstance(value.get("datasource"), dict):
                value["datasource"]["name"] = datasource
            for child in value.values():
                rewrite(child)
        elif isinstance(value, list):
            for child in value:
                rewrite(child)
    rewrite(spec)
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
    groups = zabbix.rpc("hostgroup.get", {"output": ["groupid"], "filter": {"name": [group]}})
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
                                   "filter": {"status": "0"}})
    hosts.sort(key=lambda host: ((host.get("name") or host["host"]).casefold(), int(host["hostid"])))
    changed = 0
    for host in hosts:
        changed += upsert(grafana, "/apis/dashboard.grafana.app/v2/namespaces/default/dashboards",
                          render(template, host, group, datasource))
    # Update only after every dashboard is available. Never delete dashboards.
    playlist = resource("playlist.grafana.app/v1", "Playlist", "zabbix-linux-hosts",
                        {"title": "Zabbix — Linux devices", "interval": interval,
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
    return value


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    period = max(10, int(os.getenv("SYNC_SECONDS", "60")))
    while True:
        try:
            tokens = [read_token(service) for service in ("zabbix", "grafana")]
            template = json.loads(Path("/app/template.json").read_text())
            if template.get("apiVersion") != "dashboard.grafana.app/v2":
                raise ValueError("Expected Grafana v2 dashboard template")
            sync(API(os.getenv("ZABBIX_URL", "http://zabbix-web-nginx-mysql:8080/api_jsonrpc.php"), tokens[0]),
                 API(os.getenv("GRAFANA_URL", "http://grafana:3000"), tokens[1]), template,
                 os.getenv("ZABBIX_HOST_GROUP", "Linux servers"),
                 os.getenv("GRAFANA_DATASOURCE_UID", "zabbix"),
                 os.getenv("PLAYLIST_INTERVAL", "30s"))
        except Exception as error:
            # Unexpected errors are identified without dumping potentially sensitive bodies.
            if isinstance(error, (RuntimeError, ValueError, FileNotFoundError)):
                LOG.error("Sync failed: %s", error)
            else:
                LOG.error("Sync failed: %s", type(error).__name__)
        time.sleep(period)


if __name__ == "__main__":
    main()
