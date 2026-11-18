import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_sync import Grafana, TEMPLATE, sync
import customer_dashboards as customers


CONFIG = [{'id': 'musteri01', 'name': 'Firma 01', 'group': 'Customers/musteri01',
           'proxy': 'proxy-musteri01', 'proxy_host': 'proxy-health-musteri01'},
          {'id': 'musteri02', 'name': 'Firma 02', 'group': 'Customers/musteri02',
           'proxy': 'proxy-musteri02', 'proxy_host': 'proxy-health-musteri02'}]


class Zabbix:
    def __init__(self):
        self.calls = []
        self.groups = [{'groupid': str(10 + i), 'name': c['group']} for i, c in enumerate(CONFIG)]
        self.hosts = [{'hostid': '101', 'host': 'linux', 'name': 'Linux PC',
                       'hostgroups': [self.groups[0]], 'parentTemplates': [{'host': 'Essential Items'}]},
                      {'hostid': '102', 'host': 'windows', 'name': 'Windows PC',
                       'hostgroups': [self.groups[1]], 'parentTemplates': [{'host': 'Essential Items Windows'}]}]

    def rpc(self, method, params):
        self.calls.append((method, params))
        if method == 'hostgroup.get':
            return copy.deepcopy(self.groups)
        if method == 'host.get':
            return copy.deepcopy(self.hosts)
        raise AssertionError('Only read-only group and host discovery is expected')


class CustomerTests(unittest.TestCase):
    def setUp(self):
        self.zabbix, self.grafana = Zabbix(), Grafana()

    def run_sync(self):
        return customers.sync_customers(sync, self.zabbix, self.grafana, TEMPLATE, CONFIG, 'my-source')

    def test_live_queries_shared_detail_navigation_and_idempotency(self):
        before = copy.deepcopy(TEMPLATE)
        self.assertEqual(self.run_sync(), 6)
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(before, TEMPLATE)
        self.assertEqual(len(self.grafana.resources), 6)
        self.assertFalse(any(r['kind'] == 'Playlist' for r in self.grafana.resources.values()))
        detail = self.grafana.resources[customers.DASHBOARDS + '/' + customers.DEVICE]['spec']
        self.assertNotIn('panel-6', detail['elements'])
        self.assertIn('panel-age', detail['elements'])
        host = next(v['spec'] for v in detail['variables'] if v['spec']['name'] == 'Host')
        self.assertEqual(host['query']['spec']['group'], '$Group')
        self.assertEqual(host['query']['spec']['host'], '/.*/')
        for panel in detail['elements'].values():
            for query in panel['spec']['data']['spec']['queries']:
                self.assertEqual(query['spec']['query']['spec']['group']['filter'], '$Group')
                self.assertEqual(query['spec']['query']['spec']['host']['filter'], '$Host')
        customer = self.grafana.resources[customers.DASHBOARDS + '/zbx-customer-musteri02']['spec']
        content = customer['elements']['panel-1']['spec']['vizConfig']['spec']['options']['content']
        self.assertIn('Windows PC', content)
        self.assertNotIn('Linux PC', content)
        self.assertIn('var-Group=Customers%2Fmusteri02', content)
        for element in customer['elements'].values():
            for query in element['spec']['data']['spec']['queries']:
                q = query['spec']['query']['spec']
                expected = customers.exact('Monitoring/Proxies' if q.get('item', {}).get('filter') == 'Proxy heartbeat age' else CONFIG[1]['group'])
                self.assertEqual(q['group']['filter'], expected)

    def test_no_group_access_does_not_modify_existing_dashboards(self):
        self.run_sync()
        before = copy.deepcopy(self.grafana.resources)
        self.zabbix.groups = []
        with self.assertRaisesRegex(RuntimeError, 'Host group|group'):
            self.run_sync()
        self.assertEqual(before, self.grafana.resources)

    def test_partial_customer_access_does_not_modify_existing_dashboards(self):
        self.run_sync()
        before = copy.deepcopy(self.grafana.resources)
        self.zabbix.groups = self.zabbix.groups[:1]
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(before, self.grafana.resources)

    def test_cross_customer_membership_and_duplicate_names_rejected_before_writes(self):
        self.zabbix.hosts[0]['hostgroups'] = self.zabbix.groups
        with self.assertRaises(ValueError):
            self.run_sync()
        self.assertEqual(self.grafana.writes, 0)
        self.zabbix.hosts[0]['hostgroups'] = self.zabbix.groups[:1]
        other = copy.deepcopy(self.zabbix.hosts[0]); other['hostid'] = '103'
        self.zabbix.hosts.append(other)
        with self.assertRaises(ValueError):
            self.run_sync()
        self.assertEqual(self.grafana.writes, 0)

    def test_removing_device_updates_navigation_without_deleting_other_resources(self):
        self.run_sync()
        self.zabbix.hosts = []
        self.run_sync()
        self.assertEqual(len(self.grafana.resources), 6)
        content = self.grafana.resources[customers.DASHBOARDS + '/zbx-customer-musteri01']['spec']['elements']['panel-1']['spec']['vizConfig']['spec']['options']['content']
        self.assertIn('health is unknown', content)
        self.assertNotIn('Linux PC', content)

    def test_dashboard_ownership_collision_is_not_overwritten(self):
        self.grafana.resources[customers.DASHBOARDS + '/' + customers.DEVICE] = {'metadata': {'annotations': {}}}
        with self.assertRaisesRegex(RuntimeError, 'unmanaged'):
            self.run_sync()
        self.assertEqual(self.grafana.writes, 0)

    def test_configuration_disabled_customers_uniqueness_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'customers.json'
            config = copy.deepcopy(CONFIG)
            config[1]['enabled'] = False
            path.write_text(json.dumps({'version': 1, 'customers': config}))
            self.assertEqual(len(customers.load_customers(path)), 1)
            for change in ({'id': 'bad\nvalue'}, {'enabled': 'false'}, {'proxy': CONFIG[0]['proxy']}, {'group': CONFIG[0]['group']}):
                bad = copy.deepcopy(config); bad[1].update(change)
                path.write_text(json.dumps({'version': 1, 'customers': bad}))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    customers.load_customers(path)

    def test_unknown_and_severity_are_not_conflated(self):
        self.run_sync()
        overview = self.grafana.resources[customers.DASHBOARDS + '/' + customers.OVERVIEW]['spec']
        stats = [p['spec'] for p in overview['elements'].values() if p['spec']['vizConfig']['group'] == 'stat']
        for stat in stats:
            defaults = stat['vizConfig']['spec']['fieldConfig']['defaults']
            self.assertEqual(defaults['noValue'], 'UNKNOWN')
            if 'active problems' in stat['title']:
                self.assertEqual(defaults['thresholds']['steps'][0]['color'], 'gray')
                q = stat['data']['spec']['queries'][0]['spec']['query']['spec']
                self.assertTrue(q['options']['count'])
                self.assertFalse(q['options']['useTimeRange'])

    def test_optional_checks_and_hardware_are_shared_and_scoped(self):
        self.zabbix.hosts.extend([
            {'hostid': '103', 'host': 'idrac', 'name': 'Dell controller',
             'hostgroups': [self.zabbix.groups[0]], 'parentTemplates': [{'host': 'Dell iDRAC by SNMP'}]},
            {'hostid': '104', 'host': 'website', 'name': 'Company website',
             'hostgroups': [self.zabbix.groups[0]], 'parentTemplates': [{'host': 'Website availability'}]}])
        self.run_sync()
        customer = self.grafana.resources[customers.DASHBOARDS + '/zbx-customer-musteri01']['spec']
        text = customer['elements']['panel-1']['spec']['vizConfig']['spec']['options']['content']
        self.assertIn('/d/zbx-device-hardware?', text)
        self.assertIn('/d/zbx-device-checks?', text)
        age_titles = [p['spec']['title'] for p in customer['elements'].values() if 'data age' in p['spec']['title']]
        self.assertFalse(any('Dell controller' in title or 'Company website' in title for title in age_titles))
        for uid in (customers.CHECKS, customers.HARDWARE):
            spec = self.grafana.resources[customers.DASHBOARDS + '/' + uid]['spec']
            for p in spec['elements'].values():
                for q in p['spec']['data']['spec']['queries']:
                    self.assertEqual(q['spec']['query']['spec']['group']['filter'], '$Group')
                    self.assertEqual(q['spec']['query']['spec']['host']['filter'], '$Host')
        hardware = self.grafana.resources[customers.DASHBOARDS + '/' + customers.HARDWARE]['spec']
        self.assertEqual(hardware['elements']['panel-1']['spec']['data']['spec']['queryOptions']['timeFrom'], '5m')
        checks = self.grafana.resources[customers.DASHBOARDS + '/' + customers.CHECKS]['spec']
        service = checks['elements']['panel-1']['spec']['vizConfig']['spec']['fieldConfig']['defaults']
        process = checks['elements']['panel-2']['spec']['vizConfig']['spec']['fieldConfig']['defaults']
        self.assertEqual(service['thresholds']['steps'][0]['color'], 'green')
        self.assertEqual(process['thresholds']['steps'][0]['color'], 'red')

    def test_hundred_devices_do_not_generate_hundred_dashboards(self):
        self.zabbix.hosts = [
            {'hostid': str(i + 100), 'host': 'pc-' + str(i), 'name': 'PC ' + str(i),
             'hostgroups': [self.zabbix.groups[i % 2]], 'parentTemplates': [{'host': 'Essential Items'}]}
            for i in range(100)]
        self.run_sync()
        self.assertEqual(len(self.grafana.resources), len(CONFIG) + 4)
        self.assertEqual(self.run_sync(), 0)
        for resource in self.grafana.resources.values():
            s = resource['spec']
            ids = [p['spec']['id'] for p in s['elements'].values()]
            self.assertEqual(len(ids), len(set(ids)))
            references = [entry['spec']['element']['name'] for entry in s['layout']['spec']['items']]
            self.assertEqual(set(references), set(s['elements']))
