import unittest
from unittest.mock import Mock, patch

import import_template as importer


class ImportTests(unittest.TestCase):
    def test_active_variant_keeps_dependent_items_and_separates_uuids(self):
        source = importer.TEMPLATE.read_text()
        active = importer.active_source(source)
        self.assertEqual(active, importer.active_source(source))
        self.assertIn("template: 'Essential Items Active'", active)
        self.assertEqual(active.count('type: DEPENDENT'), source.count('type: DEPENDENT'))
        self.assertEqual(active.count('key:'), source.count('key:'))
        self.assertGreater(active.count('type: ZABBIX_ACTIVE'), 8)
        self.assertNotIn('ee98f9af52d5434ba65001c4cb001eaf', active)

    def test_import_preserves_missing_objects_and_verifies_template(self):
        call = Mock(side_effect=['session', True, [{'templateid': '42'}], True])
        with patch.object(importer, 'read_env', return_value={'ZABBIX_ADMIN_PASSWORD': 'test-password'}):
            importer.import_template(call)
        request = call.call_args_list[1]
        self.assertEqual(request.args[0], 'configuration.import')
        self.assertIn("template: 'Essential Items'", request.args[1]['source'])
        for rule in request.args[1]['rules'].values():
            self.assertFalse(rule.get('deleteMissing', False))
        self.assertEqual(call.call_args_list[-1].args, ('user.logout', [], 'session'))

    def test_failed_import_logs_out_without_verification(self):
        call = Mock(side_effect=['session', RuntimeError('import failed'), True])
        with patch.object(importer, 'read_env', return_value={'ZABBIX_ADMIN_PASSWORD': 'test-password'}):
            with self.assertRaisesRegex(RuntimeError, 'import failed'):
                importer.import_template(call)
        self.assertEqual(call.call_count, 3)
        self.assertEqual(call.call_args_list[-1].args[0], 'user.logout')
