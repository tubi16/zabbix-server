import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE = Path(__file__).with_name("sync.py")
spec = importlib.util.spec_from_file_location("host_sync", MODULE)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
TEMPLATE = json.loads((MODULE.parents[1] / "templates/linux-template.json").read_text())


class Grafana:
    def __init__(self):
        self.resources = {}
        self.writes = 0
        self.fail_dashboard = False
        self.folders = {}

    def request(self, method, path, data=None, missing_ok=False):
        if path.startswith("/api/search?type=dash-folder"):
            return copy.deepcopy(list(self.folders.values()))
        if path.startswith("/api/folders"):
            if method == "POST":
                self.folders[data["uid"]] = copy.deepcopy(data)
                return data
            return copy.deepcopy(self.folders.get(path.rsplit("/", 1)[-1]))
        if path.startswith("/api/datasources/"):
            return {"type": "alexanderzobnin-zabbix-datasource"}
        if method == "GET":
            return copy.deepcopy(self.resources.get(path))
        if self.fail_dashboard and "dashboard.grafana.app" in path:
            raise RuntimeError("Simulated dashboard write failure")
        data = copy.deepcopy(data)
        if method == "POST":
            path += "/" + data["metadata"]["name"]
            if path in self.resources:
                raise AssertionError("Duplicate create")
        else:
            assert data["metadata"]["resourceVersion"] == self.resources[path]["metadata"]["resourceVersion"]
        self.writes += 1
        data["metadata"]["resourceVersion"] = str(self.writes)
        self.resources[path] = data
        return data


class Zabbix:
    def __init__(self):
        self.hosts = [{"hostid": "101", "host": "pc1", "name": "PC (home)"}]
        self.groups = [{"groupid": "2"}]

    def rpc(self, method, params):
        if method == "hostgroup.get":
            return self.groups
        assert params["groupids"] == ["2"] and params["filter"] == {"status": "0"}
        return self.hosts


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.zabbix, self.grafana = Zabbix(), Grafana()

    def run_sync(self):
        sync.sync(self.zabbix, self.grafana, TEMPLATE, "Linux servers", "my-source", "30s")

    def test_template_scoping_and_no_mutation(self):
        before = copy.deepcopy(TEMPLATE)
        dashboard = sync.render(TEMPLATE, self.zabbix.hosts[0], "Linux servers", "my-source")
        self.assertEqual(TEMPLATE, before)
        self.assertEqual(dashboard["metadata"]["name"], "zbx-host-101")
        self.assertEqual(dashboard["metadata"]["annotations"][sync.FOLDER_ANNOTATION], sync.FOLDER_UID)
        self.assertEqual(dashboard["spec"]["timeSettings"]["from"], "now-1h")
        for variable in dashboard["spec"]["variables"]:
            config = variable["spec"]
            self.assertEqual(config["query"]["datasource"]["name"], "my-source")
            if config["name"] == "Host":
                self.assertEqual(config["current"]["value"], "PC (home)")
                self.assertEqual(config["query"]["spec"]["host"], r"/^PC\ \(home\)$/")

    def test_idempotency_add_rename_remove_and_restart(self):
        self.run_sync()
        self.assertEqual(self.grafana.writes, 2)
        self.run_sync()
        self.assertEqual(self.grafana.writes, 2)
        self.zabbix.hosts.append({"hostid": "102", "host": "pc2", "name": "Cuffyn"})
        self.run_sync()
        self.assertEqual(self.grafana.writes, 4)
        self.zabbix.hosts[0]["name"] = "Renamed"
        self.run_sync()
        self.assertEqual(self.grafana.writes, 5)  # renamed dashboard; playlist order unchanged
        self.zabbix.hosts = []
        self.run_sync()
        playlist = next(v for v in self.grafana.resources.values() if v["kind"] == "Playlist")
        self.assertEqual(playlist["spec"]["items"], [])
        self.assertEqual(len(self.grafana.resources), 3)  # no deletion
        self.run_sync()
        self.assertEqual(self.grafana.writes, 6)

    def test_failed_dashboard_does_not_update_playlist(self):
        self.run_sync()
        before = copy.deepcopy(self.grafana.resources)
        self.zabbix.hosts.append({"hostid": "102", "host": "pc2", "name": "Cuffyn"})
        self.grafana.fail_dashboard = True
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(self.grafana.resources, before)

    def test_missing_group_does_not_clear_playlist(self):
        self.run_sync()
        before = copy.deepcopy(self.grafana.resources)
        self.zabbix.groups = []
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(self.grafana.resources, before)

    def test_uid_collision_is_not_overwritten(self):
        dashboard = sync.render(TEMPLATE, self.zabbix.hosts[0], "Linux servers", "my-source")
        path = "/apis/dashboard.grafana.app/v2/namespaces/default/dashboards/zbx-host-101"
        self.grafana.resources[path] = dashboard
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(self.grafana.writes, 0)

    def test_existing_managed_dashboard_moves_into_folder(self):
        self.run_sync()
        path = "/apis/dashboard.grafana.app/v2/namespaces/default/dashboards/zbx-host-101"
        metadata = self.grafana.resources[path]["metadata"]
        metadata["annotations"].pop(sync.FOLDER_ANNOTATION)
        metadata["annotations"][sync.DIGEST] = "legacy-config-hash"
        self.run_sync()
        self.assertEqual(self.grafana.resources[path]["metadata"]["annotations"][sync.FOLDER_ANNOTATION],
                         sync.FOLDER_UID)
        self.assertEqual(len(self.grafana.resources), 2)

    def test_environment_token_precedes_files(self):
        with patch.dict(sync.os.environ, {"GRAFANA_SERVICE_TOKEN": " test-value "}):
            with patch.object(sync.Path, "read_text", side_effect=AssertionError("Unexpected file read")):
                self.assertEqual(sync.read_token("grafana"), "test-value")

    def test_windows_queries_and_os_label(self):
        host = {"hostid": "201", "host": "win-pc", "name": "Office PC",
                "parentTemplates": [{"host": "Essential Items Windows Active"}]}
        before = copy.deepcopy(TEMPLATE)
        dashboard = sync.render(TEMPLATE, host, "Windows servers", "my-source")
        self.assertEqual(TEMPLATE, before)
        spec = dashboard["spec"]
        self.assertEqual(spec["title"], "Windows — Office PC [201]")
        self.assertIn("os:Windows", spec["tags"])
        queries = [q["spec"]["query"]["spec"]["item"]["filter"]
                   for p in spec["elements"].values()
                   for q in p["spec"]["data"]["spec"]["queries"]]
        self.assertIn("System Uptime", queries)
        self.assertIn("CPU Utilization", queries)
        self.assertIn("/^Active Download Speed:/", queries)
        self.assertIn("/^Active Upload Speed:/", queries)
        self.assertIn("/^Process user CPU time rate:/", queries)
        self.assertNotIn("System Time", queries)
        defaults = spec["elements"]["panel-3"]["spec"]["vizConfig"]["spec"]["fieldConfig"]["defaults"]
        self.assertEqual(defaults["unit"], "percent")
        self.assertEqual(defaults["max"], 100)

    def test_os_detection_precedence_and_unknown(self):
        host = {"parentTemplates": [{"host": "Essential Items Windows"}],
                "inventory": {"os": "Ubuntu Linux"}}
        self.assertEqual(sync.host_os(host, "Linux servers"), "Windows")
        self.assertEqual(sync.host_os({"inventory": {"os": "Arch Linux"}}, "Devices"), "Linux")
        self.assertEqual(sync.host_os({}, "Devices"), "Unknown OS")
        self.assertEqual(sync.host_os({}, "Windows servers"), "Windows")

    def test_mixed_hosts_share_existing_playlist_and_are_scoped(self):
        linux = {"hostid": "101", "host": "linux", "name": "Linux PC",
                 "hostgroups": [{"groupid": "2", "name": "Linux servers"}]}
        windows = {"hostid": "201", "host": "windows", "name": "Windows PC",
                   "hostgroups": [{"groupid": "3", "name": "Windows servers"}],
                   "parentTemplates": [{"host": "Essential Items Windows"}]}

        class MixedZabbix:
            def rpc(inner, method, params):
                if method == "hostgroup.get":
                    self.assertEqual(params["filter"]["name"], ["Linux servers", "Windows servers"])
                    return [{"groupid": "2", "name": "Linux servers"},
                            {"groupid": "3", "name": "Windows servers"}]
                self.assertEqual(params["groupids"], ["2", "3"])
                self.assertEqual(params["filter"], {"status": "0"})
                self.assertIn("selectParentTemplates", params)
                return [linux, windows, windows]

        for _ in range(2):
            sync.sync(MixedZabbix(), self.grafana, TEMPLATE,
                      "Linux servers,Windows servers", "my-source", "30s")
        self.assertEqual(self.grafana.writes, 3)
        playlists = [r for r in self.grafana.resources.values() if r["kind"] == "Playlist"]
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0]["metadata"]["name"], "zabbix-linux-hosts")
        self.assertEqual(playlists[0]["spec"]["title"], "Zabbix — Devices")
        self.assertEqual([i["value"] for i in playlists[0]["spec"]["items"]], ["zbx-host-101", "zbx-host-201"])
        for r in self.grafana.resources.values():
            if r["kind"] != "Dashboard":
                continue
            group = next(v["spec"]["current"]["value"] for v in r["spec"]["variables"]
                         if v["spec"]["name"] == "Group")
            self.assertEqual(group, "Windows servers" if r["metadata"]["name"] == "zbx-host-201" else "Linux servers")


if __name__ == "__main__":
    unittest.main()
