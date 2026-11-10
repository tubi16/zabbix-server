import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import register_monitoring as register


class RegistrationTests(unittest.TestCase):
    def test_proxy_plan_never_writes_and_apply_requires_psk(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / 'proxy.psk'
            key.write_text('ab' * 32)
            key.chmod(0o600)
            args = argparse.Namespace(kind='proxy', name='site1-proxy', identity=None, key=key, apply=False)
            call = Mock(side_effect=['session', [], True])
            with patch.object(register, 'read_env', return_value={'ZABBIX_ADMIN_PASSWORD': 'test'}):
                register.registration(args, call)
            self.assertNotIn('proxy.create', [c.args[0] for c in call.call_args_list])
            args.apply = True
            call = Mock(side_effect=['session', [], {'proxyids': ['1']}, True])
            with patch.object(register, 'read_env', return_value={'ZABBIX_ADMIN_PASSWORD': 'test'}):
                register.registration(args, call)
            params = call.call_args_list[2].args[1]
            self.assertEqual(params['tls_accept'], 2)
            self.assertEqual(params['operating_mode'], 0)
            self.assertEqual(params['tls_psk_identity'], 'site1-proxy-server')
            self.assertNotIn('allowed_addresses', params)

    def test_existing_record_is_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / 'key'
            key.write_text('ab' * 32)
            key.chmod(0o600)
            args = argparse.Namespace(kind='proxy', name='site1-proxy', identity=None, key=key, apply=True)
            call = Mock(side_effect=['session', [{'proxyid': '1'}], True])
            with patch.object(register, 'read_env', return_value={'ZABBIX_ADMIN_PASSWORD': 'test'}):
                with self.assertRaisesRegex(ValueError, 'mevcut'):
                    register.registration(args, call)
            self.assertEqual(call.call_args_list[-1].args[0], 'user.logout')

    def test_host_is_assigned_to_proxy_with_active_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / 'key'
            key.write_text('ab' * 32)
            key.chmod(0o600)
            args = argparse.Namespace(kind='host', name='site1-pc1', identity=None, key=key,
                                      apply=True, proxy='site1-proxy', group='Linux servers')
            call = Mock(side_effect=['session', [], [{'proxyid': '3'}], [{'templateid': '4'}],
                                     [{'groupid': '5'}], {'hostids': ['6']}, True])
            with patch.object(register, 'read_env', return_value={'ZABBIX_ADMIN_PASSWORD': 'test'}):
                register.registration(args, call)
            params = call.call_args_list[5].args[1]
            self.assertEqual(params['monitored_by'], 1)
            self.assertEqual(params['proxyid'], '3')
            self.assertEqual(params['tls_accept'], 2)
            self.assertNotIn('interfaces', params)
