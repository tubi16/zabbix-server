import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import enroll
import psk_common



class FakeAPI:
    def __init__(self, host=None):
        self.host = copy.deepcopy(host)
        self.creates = 0
        self.writes = []
        self.fail_registration = False

    def __call__(self, method, params, session=None):
        if method == "hostgroup.get":
            return [{"groupid": "2"}]
        if method == "template.get":
            return [{"templateid": "99"}]
        if method == "host.get":
            return [copy.deepcopy(self.host)] if self.host else []
        if method in ("host.create", "host.update"):
            if self.fail_registration:
                raise RuntimeError("Simulated registration failure")
            self.writes.append(method)
            if method == "host.create":
                self.creates += 1
                self.host = {"hostid": "42"}
            self.host.update(copy.deepcopy(params))
            if "groups" in params:
                self.host["hostgroups"] = self.host.pop("groups")
            if "templates" in params:
                self.host["parentTemplates"] = self.host.pop("templates")
            for interface in self.host.get("interfaces", []):
                interface.setdefault("interfaceid", "12")
            return {"hostids": [self.host["hostid"]]}
        if method == "hostinterface.update":
            self.writes.append(method)
            self.host["interfaces"][0].update(params)
            return {"interfaceids": [params["interfaceid"]]}
        if method == "hostinterface.create":
            self.writes.append(method)
            self.host["interfaces"] = [{"interfaceid": "12", **params}]
            return {"interfaceids": ["12"]}
        raise AssertionError(method)


class Runner:
    def __init__(self):
        self.commands = []
        self.fail_psk = False
        self.fail_strict = False
        self.accept_plaintext = False

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if command[0] == "sudo" and "--strict" in command and self.fail_strict:
            raise subprocess.CalledProcessError(1, command)
        if "input" in kwargs:
            return subprocess.CompletedProcess(command, 1 if self.fail_psk else 0,
                                               stdout=b"" if self.fail_psk else b"1\n")
        if "unencrypted" in command:
            return subprocess.CompletedProcess(command, 0 if self.accept_plaintext else 1,
                                               stdout=b"1\n" if self.accept_plaintext else b"")
        return subprocess.CompletedProcess(command, 0, stdout=b"")


def existing_host():
    return {"hostid": "42", "host": "NewPC", "tls_connect": "1", "tls_accept": "1",
            "hostgroups": [{"groupid": "7"}], "parentTemplates": [{"templateid": "88"}],
            "tags": [{"tag": "site", "value": "office"}],
            "interfaces": [{"interfaceid": "12", "type": "1", "main": "1", "useip": "1",
                            "ip": "192.0.2.3", "dns": "", "port": "10050"}]}


class EnrollTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.private = Path(self.temporary.name) / "private"
        self.agent_source = Path(self.temporary.name) / "external-agent-repo"
        self.agent_source.mkdir()
        (self.agent_source / "install.py").write_text("# Test fixture; subprocesses are mocked\n")
        self.args = enroll.arguments(["--host", "NewPC", "--address", "192.0.2.5", "--local",
                                     "--server", "192.0.2.1", "--agent-source", str(self.agent_source)])
        self.api = FakeAPI()
        self.runner = Runner()
        self.addCleanup(patch.stopall)
        patch("builtins.print").start()

    def enrollment(self):
        return enroll.Enrollment(self.args, call=self.api, run=self.runner, private=self.private)

    def test_new_host_end_to_end_and_repeat(self):
        self.enrollment().execute()
        key = (self.private / "NewPC.psk").read_text()
        self.enrollment().execute()
        self.assertEqual(self.api.creates, 1)
        self.assertEqual((self.private / "NewPC.psk").read_text(), key)
        self.assertEqual(self.api.host["tls_connect"], 2)
        self.assertEqual(self.api.host["tls_accept"], 2)
        state = json.loads((self.private / "NewPC.enrollment.json").read_text())
        self.assertEqual(state["phase"], "complete")
        self.assertIsNone(state["original"])

    def test_existing_host_keeps_groups_templates_and_tags(self):
        self.api.host = existing_host()
        self.enrollment().execute()
        self.assertEqual({g["groupid"] for g in self.api.host["hostgroups"]}, {"2", "7"})
        self.assertEqual({g["templateid"] for g in self.api.host["parentTemplates"]}, {"88", "99"})
        self.assertIn({"tag": "site", "value": "office"}, self.api.host["tags"])
        self.assertEqual(self.api.host["interfaces"][0]["ip"], "192.0.2.5")

    def test_failed_psk_probe_never_updates_server(self):
        self.runner.fail_psk = True
        with self.assertRaisesRegex(RuntimeError, "PSK probe"):
            self.enrollment().execute()
        self.assertEqual(self.api.writes, [])
        self.assertFalse(any("--strict" in command for command, _ in self.runner.commands))

    def test_failed_registration_does_not_close_plaintext(self):
        self.api.fail_registration = True
        with self.assertRaises(RuntimeError):
            self.enrollment().execute()
        self.assertFalse(any("--strict" in command for command, _ in self.runner.commands))

    def test_strict_failure_can_resume_without_rotating_or_duplicating(self):
        self.runner.fail_strict = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.enrollment().execute()
        key = (self.private / "NewPC.psk").read_text()
        self.runner.fail_strict = False
        self.enrollment().execute()
        self.assertEqual(self.api.creates, 1)
        self.assertEqual((self.private / "NewPC.psk").read_text(), key)

    def test_plaintext_acceptance_is_not_reported_as_complete(self):
        self.runner.accept_plaintext = True
        with self.assertRaisesRegex(RuntimeError, "still accepts plaintext"):
            self.enrollment().execute()
        state = json.loads((self.private / "NewPC.enrollment.json").read_text())
        self.assertEqual(state["phase"], "server-psk")

    def test_unmanaged_encryption_is_not_overwritten(self):
        self.api.host = existing_host()
        self.api.host["tls_connect"] = "2"
        with self.assertRaisesRegex(RuntimeError, "unmanaged"):
            self.enrollment().execute()
        self.assertEqual(self.runner.commands, [])
        self.assertEqual(self.api.writes, [])

    def test_key_uses_stdin_not_arguments(self):
        self.enrollment().execute()
        key = (self.private / "NewPC.psk").read_text().strip()
        for command, kwargs in self.runner.commands:
            self.assertNotIn(key, " ".join(command))
            if "input" in kwargs:
                self.assertEqual(kwargs["input"].strip(), key.encode())

    def test_rollback_disables_new_host_without_deleting_it(self):
        self.enrollment().execute()
        self.enrollment().rollback()
        self.assertEqual(self.api.host["status"], 1)
        self.assertEqual(self.api.creates, 1)

    def test_rollback_restores_existing_tls_settings(self):
        self.api.host = existing_host()
        self.enrollment().execute()
        self.enrollment().rollback()
        self.assertEqual(self.api.host["tls_connect"], "1")
        self.assertEqual(self.api.host["tls_accept"], "1")

    def test_remote_transfer_does_not_include_admin_credentials(self):
        self.args.ssh = "cuffyn"
        self.args.local = False
        self.enrollment().execute()
        transfer = next(command for command, _ in self.runner.commands if command[0] == "scp")
        self.assertFalse(any(".env" in item for item in transfer))
        self.assertTrue(any(item.endswith("install.py") for item in transfer))
        self.assertFalse(any(item.endswith("psk_common.py") for item in transfer))

    def test_external_agent_source_is_required_before_any_api_calls(self):
        (self.agent_source / "install.py").unlink()
        with self.assertRaisesRegex(RuntimeError, "Agent source not found"):
            self.enrollment().execute()
        self.assertEqual(self.api.writes, [])
        self.assertEqual(self.runner.commands, [])


class HelpersTests(unittest.TestCase):
    def test_unsafe_host_names_are_rejected(self):
        for name in ["../pc", "pc/name", "-option", "pc;touch", "", "a" * 65]:
            with self.assertRaises(argparse.ArgumentTypeError):
                psk_common.host_name(name)

    def test_unique_keys_and_existing_key_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "private"
            one = psk_common.ensure_key("PC1", directory)
            two = psk_common.ensure_key("PC2", directory)
            self.assertNotEqual(one.read_text(), two.read_text())
            self.assertEqual(psk_common.ensure_key("PC1", directory).read_text(), one.read_text())
            self.assertEqual(one.stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)




    def test_invalid_existing_key_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "PC.psk").write_text("invalid")
            with self.assertRaises(ValueError):
                psk_common.ensure_key("PC", directory)
            self.assertEqual((directory / "PC.psk").read_text(), "invalid")



if __name__ == "__main__":
    unittest.main()
