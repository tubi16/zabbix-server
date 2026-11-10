import unittest
import re
import uuid
from unittest.mock import Mock, patch

import import_template as importer


class ImportTests(unittest.TestCase):
    def test_active_identifiers_match_zabbix_uuidv4_validation(self):
        source = importer.TEMPLATE.read_text()
        active = importer.active_source(source)
        identifiers = re.findall(r'(?m)^\s*(?:- )?uuid: ([0-9a-f]{32})$', active)
        self.assertTrue(identifiers)
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for value in identifiers:
            self.assertEqual(uuid.UUID(hex=value).version, 4)
        self.assertEqual(active, importer.active_source(source))

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

    def test_active_triggers_reference_active_template_without_item_type(self):
        active = importer.active_source(importer.TEMPLATE.read_text())
        self.assertNotIn('/Essential Items/', active)
        self.assertEqual(active.count('expression:'), 8)
        trigger_blocks = re.findall(
            r'(?m)^            - uuid:[^\n]*\n(?:^ {14,}[^\n]*\n)*', active)
        trigger_blocks = [block for block in trigger_blocks if 'expression:' in block]
        self.assertEqual(len(trigger_blocks), 5)
        for block in trigger_blocks:
            self.assertNotIn('type: ZABBIX_ACTIVE', block)
        self.assertEqual(active.count('value: telegram'), 5)

    def test_failed_import_logs_out_without_verification(self):
        call = Mock(side_effect=['session', RuntimeError('import failed'), True])
        with patch.object(importer, 'read_env', return_value={'ZABBIX_ADMIN_PASSWORD': 'test-password'}):
            with self.assertRaisesRegex(RuntimeError, 'import failed'):
                importer.import_template(call)
        self.assertEqual(call.call_count, 3)
        self.assertEqual(call.call_args_list[-1].args[0], 'user.logout')
