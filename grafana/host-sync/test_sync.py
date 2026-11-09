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
        self.assertEqual(self.grafana.writes, 6)  # dashboard and playlist sort order
        self.zabbix.hosts = []
        self.run_sync()
        playlist = next(v for v in self.grafana.resources.values() if v["kind"] == "Playlist")
        self.assertEqual(playlist["spec"]["items"], [])
        self.assertEqual(len(self.grafana.resources), 3)  # no deletion
        self.run_sync()
        self.assertEqual(self.grafana.writes, 7)

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


if __name__ == "__main__":
    unittest.main()
