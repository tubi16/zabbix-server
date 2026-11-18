import json
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1] / 'zabbix/templates'


@unittest.skipUnless(yaml, 'PyYAML is only needed for template validation')
class RoleTests(unittest.TestCase):
    def load(self, name):
        return yaml.safe_load((ROOT / name).read_text())['zabbix_export']

    def test_explicit_lists_and_agent_modes(self):
        for stem in ('required-windows-services', 'required-processes'):
            for active in (False, True):
                name = stem + ('-active' if active else '') + '.yaml'
                t = self.load(name)['templates'][0]
                with self.subTest(template=name):
                    self.assertEqual(t['macros'][0]['value'], '[]')
                    rule = t['discovery_rules'][0]
                    self.assertEqual(rule['type'], 'SCRIPT')
                    self.assertEqual(rule['enabled_lifetime_type'], 'DISABLE_IMMEDIATELY')
                    self.assertEqual(rule['lifetime_type'], 'DELETE_NEVER')
                    item = rule['item_prototypes'][0]
                    self.assertNotIn('triggers', item)
                    self.assertIn('trigger_prototypes', item)
                    self.assertEqual(item.get('type', 'ZABBIX_PASSIVE'), 'ZABBIX_ACTIVE' if active else 'ZABBIX_PASSIVE')
                    self.assertIn('/' + t['template'] + '/', item['trigger_prototypes'][0]['expression'])
                    self.assertIn('>=3 and ', item['trigger_prototypes'][0]['expression'])

    @unittest.skipUnless(shutil.which('node'), 'Node is needed only to execute discovery JS validation')
    def test_discovery_keeps_missing_names_and_rejects_injection_and_duplicates(self):
        runner = '''const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));
        try { const f = new Function('value', data.script);
        console.log(f(JSON.stringify({names:JSON.stringify(data.names)}))); }
        catch (error) { process.exit(2); }'''
        for name, macro in [('required-processes.yaml', '{#PROCESS.NAME}'), ('required-windows-services.yaml', '{#SERVICE.NAME}')]:
            script = self.load(name)['templates'][0]['discovery_rules'][0]['params']
            def execute(names):
                return subprocess.run(['node', '-e', runner], input=json.dumps({'script':script, 'names':names}), capture_output=True, text=True)
            result = execute(['missing-service', 'MSSQL$INSTANCE'])
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout), [{macro:'missing-service'}, {macro:'MSSQL$INSTANCE'}])
            self.assertEqual(json.loads(execute([]).stdout), [])
            for invalid in (['a','a'], ['__proto__','__proto__'], ['bad\nServer=evil'], ['bad",state]'], [''], [1], 'not an array', ['name']*101):
                with self.subTest(template=name, invalid=invalid):
                    self.assertNotEqual(execute(invalid).returncode, 0)

    def test_optional_website_has_verified_tls_and_no_fake_valid_default(self):
        d = self.load('website-availability.yaml');t = d['templates'][0];scenario = t['httptests'][0]
        self.assertEqual(scenario['verify_peer'], 'YES')
        self.assertEqual(scenario['verify_host'], 'YES')
        self.assertEqual(t['macros'][0]['value'], 'https://example.invalid/')
        self.assertEqual(scenario['steps'][0]['status_codes'], '200-299')
        self.assertIn('>=3 and ', d['triggers'][0]['expression'])
        self.assertTrue(any('nodata(' in trigger['expression'] for trigger in d['triggers']))

    def test_broad_process_collection_is_opt_in(self):
        for path in ROOT.glob('essential-items*.yaml'):
            t = self.load(path.name)['templates'][0]
            self.assertEqual(next(i for i in t['items'] if i['key']=='proc.get[,,,summary]')['status'], 'DISABLED')
            self.assertEqual(next(r for r in t['discovery_rules'] if r['key']=='proc.discovery')['status'], 'DISABLED')
