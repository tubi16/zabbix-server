"""Semantic export checks; PyYAML is used only by these optional validation tests."""
from pathlib import Path
import re
import unittest
import uuid

try:
    import yaml
except ImportError:
    yaml = None

import import_template

ROOT = Path(__file__).resolve().parents[1] / 'zabbix/templates'


@unittest.skipUnless(yaml, 'PyYAML is needed for export validation; runtime scripts do not need it')
class StorageTemplateTests(unittest.TestCase):
    def templates(self):
        for path in ROOT.glob('essential-items*.yaml'):
            yield path, yaml.safe_load(path.read_text())['zabbix_export']['templates'][0]

    def test_discovery_structure_keys_and_migration(self):
        for path, template in self.templates():
            with self.subTest(path=path.name):
                keys = [i['key'] for i in template['items']]
                self.assertEqual(len(keys), len(set(keys)))
                legacy = next(i for i in template['items'] if i['name'] == 'Disk Usage')
                self.assertEqual(legacy['status'], 'DISABLED')
                self.assertTrue(all(t['status'] == 'DISABLED' for t in legacy['triggers']))
                rules = [r for r in template['discovery_rules'] if r['key'] == 'vfs.fs.discovery']
                self.assertEqual(len(rules), 1)
                prototypes = rules[0]['item_prototypes']
                self.assertEqual(len(prototypes), 3)
                self.assertEqual({p['key'] for p in prototypes}, {
                    'vfs.fs.size["{#FSNAME}",pused]', 'vfs.fs.size["{#FSNAME}",free]', 'vfs.fs.size["{#FSNAME}",total]'})
                trigger = prototypes[0]['trigger_prototypes'][0]
                self.assertNotIn('triggers', prototypes[0])
                self.assertIn('{$DISK.USED.HIGH:"{#FSNAME}"}', trigger['expression'])
                self.assertIn('{$DISK.USED.RECOVERY:"{#FSNAME}"}', trigger['recovery_expression'])
                self.assertIn('/' + template['template'] + '/', trigger['expression'])

    def test_active_types_keep_calculated_items_on_collector(self):
        for path, template in self.templates():
            with self.subTest(path=path.name):
                age = next(i for i in template['items'] if i['key'] == 'agent.data.age')
                self.assertEqual(age['type'], 'CALCULATED')
                self.assertEqual(age['params'], 'now()-lastclock(//system.uptime)')
                objects = template['items'] + template['discovery_rules']
                objects += [p for r in template['discovery_rules'] for p in r.get('item_prototypes', [])]
                for item in objects:
                    kind = item.get('type', 'ZABBIX_PASSIVE')
                    if kind in ('CALCULATED', 'DEPENDENT'):
                        continue
                    self.assertEqual(kind, 'ZABBIX_ACTIVE' if 'active' in path.name else 'ZABBIX_PASSIVE')

    def test_default_filters_keep_real_disks_and_exclude_temporary_filesystems(self):
        for path, template in self.templates():
            macros = {m['macro']: m['value'] for m in template['macros']}
            def accepted(name, kind):
                return (re.search(macros['{$VFS.FS.FSNAME.MATCHES}'], name)
                        and not re.search(macros['{$VFS.FS.FSNAME.NOT_MATCHES}'], name)
                        and re.search(macros['{$VFS.FS.FSTYPE.MATCHES}'], kind)
                        and not re.search(macros['{$VFS.FS.FSTYPE.NOT_MATCHES}'], kind))
            with self.subTest(path=path.name):
                if 'windows' in path.name:
                    self.assertTrue(accepted('C:', 'NTFS'))
                    self.assertTrue(accepted('D:', 'ReFS'))
                else:
                    self.assertTrue(accepted('/', 'ext4'))
                    self.assertTrue(accepted('/data', 'xfs'))
                    self.assertFalse(accepted('/run', 'tmpfs'))
                    self.assertFalse(accepted('/sys', 'sysfs'))

    def test_uuid_uniqueness_and_linux_active_export_agreement(self):
        for path, template in self.templates():
            ids = []
            def walk(value):
                if isinstance(value, dict):
                    if 'uuid' in value: ids.append(value['uuid'])
                    for child in value.values(): walk(child)
                elif isinstance(value, list):
                    for child in value: walk(child)
            walk(template)
            with self.subTest(path=path.name):
                self.assertEqual(len(ids), len(set(ids)))
                self.assertTrue(all(uuid.UUID(hex=i).version == 4 for i in ids))
        expected = yaml.safe_load(import_template.active_source((ROOT / 'essential-items.yaml').read_text()))['zabbix_export']['templates'][0]
        actual = yaml.safe_load((ROOT / 'essential-items-linux-active.yaml').read_text())['zabbix_export']['templates'][0]
        actual['name'] = expected['name']
        actual['description'] = expected['description']
        self.assertEqual(expected, actual)

    def test_proxy_health_runs_without_agent_and_has_missing_data_alarm(self):
        template = yaml.safe_load((ROOT / 'customer-proxy-health.yaml').read_text())['zabbix_export']['templates'][0]
        self.assertEqual([i['type'] for i in template['items']], ['INTERNAL', 'CALCULATED'])
        self.assertIn('lastaccess', template['items'][0]['key'])
        self.assertEqual(template['items'][1]['params'], 'now()-last(//zabbix[proxy,"{$PROXY.NAME}",lastaccess])')
        self.assertTrue(any('nodata(' in t['expression'] for i in template['items'] for t in i.get('triggers', [])))
