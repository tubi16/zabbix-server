import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('bootstrap_admin', Path(__file__).with_name('bootstrap_admin.py'))
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(admin, 'read_env', return_value={'ZABBIX_ADMIN_PASSWORD': 'desired-password'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matching_password_never_updated(self):
        call = Mock(side_effect=['session', True])
        admin.bootstrap(call)
        self.assertEqual([c.args[0] for c in call.call_args_list], ['user.login', 'user.logout'])

    def test_factory_update_and_new_login_verified(self):
        call = Mock(side_effect=[RuntimeError('login'), {'userid': '7', 'sessionid': 'factory'}, {}, True, 'new', True])
        admin.bootstrap(call)
        update = call.call_args_list[2]
        self.assertEqual(update.args, ('user.update', {'userid': '7', 'passwd': 'desired-password', 'current_passwd': 'zabbix'}, 'factory'))
        self.assertEqual(call.call_args_list[4].args[1]['password'], 'desired-password')

    def test_existing_different_password_never_reset(self):
        call = Mock(side_effect=RuntimeError('login'))
        with self.assertRaisesRegex(RuntimeError, 'NOT reset'):
            admin.bootstrap(call)
        self.assertEqual(call.call_count, 2)

    def test_empty_or_factory_target_rejected_without_requests(self):
        for value in ('', ' ', 'zabbix'):
            with self.subTest(value=value), patch.object(admin, 'read_env', return_value={'ZABBIX_ADMIN_PASSWORD': value}):
                call = Mock()
                with self.assertRaises(RuntimeError):
                    admin.bootstrap(call)
                call.assert_not_called()

    def test_update_failure_logs_out_without_verification(self):
        call = Mock(side_effect=[RuntimeError('login'), {'userid': '7', 'sessionid': 'factory'}, RuntimeError('update'), True])
        with self.assertRaisesRegex(RuntimeError, 'update'):
            admin.bootstrap(call)
        self.assertEqual(call.call_args_list[-1].args, ('user.logout', [], 'factory'))


if __name__ == '__main__':
    unittest.main()
