"""Read-only customer discovery and live Grafana dashboards; no Zabbix mutations."""
import copy
import json
from pathlib import Path
import re
from urllib.parse import urlencode

DASHBOARDS = '/apis/dashboard.grafana.app/v2/namespaces/default/dashboards'
FOLDER = 'zabbix-customers'
OVERVIEW = 'zbx-customers'
DEVICE = 'zbx-device'
CHECKS = 'zbx-device-checks'
HARDWARE = 'zbx-device-hardware'


def exact(value):
    return '/^' + re.escape(value).replace('/', r'\/') + '$/'


def load_customers(path):
    config = json.loads(Path(path).read_text())
    if config.get('version') != 1 or not isinstance(config.get('customers'), list):
        raise ValueError('Customer config must have version 1 and a customers list')
    customers = []
    ids, groups, proxies, health_hosts = set(), set(), set(), set()
    for entry in config['customers']:
        if not isinstance(entry, dict) or type(entry.get('enabled', True)) is not bool:
            raise ValueError('Each customer must be an object with a boolean enabled flag')
        customer = dict(entry)
        for field in ('id', 'name', 'group', 'proxy', 'proxy_host'):
            value = customer.get(field)
            if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
                raise ValueError('Each customer requires valid id, name, group, proxy and proxy_host fields')
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', customer['id']):
            raise ValueError('Customer id must be a stable lowercase identifier')
        for field, used in [('id', ids), ('group', groups), ('proxy', proxies), ('proxy_host', health_hosts)]:
            if customer[field] in used:
                raise ValueError('Customer identifiers, groups, proxies and proxy hosts must be unique')
            used.add(customer[field])
        if customer.get('enabled', True):
            customers.append(customer)
    if not customers:
        raise ValueError('Enable at least one customer in the customer config')
    return customers


def link(uid, **variables):
    return '/d/' + uid + ('?' + urlencode({'var-' + key: value for key, value in variables.items()}) if variables else '')


def markdown(value):
    return re.sub(r'([\\`*_{}\[\]()<>|#!])', r'\\\1', value)


def device_view(host):
    names = {t.get('host', '') for t in host.get('parentTemplates', [])}
    if names & {'Dell iDRAC by SNMP', 'HP iLO by SNMP'}:
        return HARDWARE, 'iDRAC/iLO'
    if 'Website availability' in names:
        return CHECKS, 'Website'
    return DEVICE, None


def query(template, datasource, group, host='/.*/', item=None, problems=False, count=False, min_severity=0):
    spec = copy.deepcopy(template['spec']['elements']['panel-2']['spec']['data']['spec']['queries'][0]['spec']['query'])
    spec['datasource']['name'] = datasource
    q = spec['spec']
    q.update({'group': {'filter': exact(group)}, 'host': {'filter': host}, 'functions': [],
              'queryType': '5' if problems else '0', 'resultFormat': 'time_series'})
    q['options'].update({'showDisabledItems': False, 'skipEmptyValues': True, 'useTrends': 'false'})
    if problems:
        q.update({'showProblems': 'problems', 'problemTags': [], 'tags': {'filter': ''}})
        q['options'].update({'limit': 200, 'severities': [0, 1, 2, 3, 4, 5],
                             'sortProblems': 'severity', 'hostsInMaintenance': False,
                             'useTimeRange': False, 'fetchHistoricalItemValue': False,
                             'symptom': False})
        if count:
            q.update({'queryType': '4', 'countTriggersBy': 'problems',
                      'triggers': {'minSeverity': min_severity, 'acknowledged': 2, 'count': True}})
            q['options']['count'] = True
            q['options']['minSeverity'] = min_severity
    else:
        q['item'] = {'filter': item}
    return spec


def panel(number, title, kind, query_spec=None, content=None, url=None, age=False, critical=False):
    options = {'showHeader': True} if kind == 'table' else {}
    defaults = {'noValue': 'UNKNOWN', 'color': {'mode': 'thresholds'}}
    if kind == 'text':
        options = {'mode': 'markdown', 'content': content}
    elif kind == 'stat':
        options = {'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                   'colorMode': 'background', 'graphMode': 'none', 'textMode': 'auto'}
        # Zero active problems does not establish that data collection is healthy.
        defaults['thresholds'] = {'mode': 'absolute', 'steps': [
            {'value': None, 'color': 'gray'}, {'value': 1, 'color': 'red' if critical else 'orange'}]}
        if age:
            defaults.update({'unit': 's', 'thresholds': {'mode': 'absolute', 'steps': [
                {'value': None, 'color': 'red'}, {'value': 0, 'color': 'green'},
                {'value': 180, 'color': 'orange'}, {'value': 300, 'color': 'red'}]}})
        defaults['mappings'] = [{'type': 'special', 'options': {'match': 'null', 'result': {'text': 'UNKNOWN', 'color': 'gray'}}}]
    if url:
        defaults['links'] = [{'title': 'Open', 'url': url, 'targetBlank': False}]
    return {'kind': 'Panel', 'spec': {'id': number, 'title': title,
        'description': 'Live Zabbix query. Missing data is UNKNOWN.' if query_spec else '',
        'links': [{'title': 'Open', 'url': url, 'targetBlank': False}] if url else [],
        'data': {'kind': 'QueryGroup', 'spec': {'queries': [] if query_spec is None else [
            {'kind': 'PanelQuery', 'spec': {'query': query_spec, 'refId': 'A', 'hidden': False}}],
            'transformations': [], 'queryOptions': {'timeFrom': '5m'} if age else {}}},
        'vizConfig': {'kind': 'VizConfig', 'group': kind, 'version': '13.0.0',
                      'spec': {'options': options, 'fieldConfig': {'defaults': defaults, 'overrides': []}}}}}


def proxy_age_table(template, customers, datasource):
    table = panel(2, 'Proxy heartbeat ages', 'table', age=True)
    spec = table['spec']
    spec['description'] = 'Latest heartbeat age in the last 5 minutes. The roster lists customer proxies awaiting data.'
    data = spec['data']['spec']
    for index, customer in enumerate(customers, 1):
        metric = query(template, datasource, 'Monitoring/Proxies',
                       exact(customer['proxy_host']), 'Proxy heartbeat age')
        metric['spec']['functions'] = [{
            'def': {'name': 'setAlias', 'category': 'Alias',
                    'params': [{'name': 'alias', 'type': 'string'}], 'defaultParams': ['']},
            'params': [customer['proxy']],
        }]
        data['queries'].append({
            'kind': 'PanelQuery',
            'spec': {'query': metric, 'refId': f'P{index}', 'hidden': False},
        })
    data['transformations'] = [
        {'kind': 'Transformation', 'group': 'reduce', 'spec': {
            'options': {'mode': 'seriesToRows', 'reducers': ['lastNotNull']}}},
        {'kind': 'Transformation', 'group': 'sortBy', 'spec': {
            'options': {'sort': [{'field': 'Field'}]}}},
        {'kind': 'Transformation', 'group': 'organize', 'spec': {
            'options': {'renameByName': {'Field': 'Proxy', 'Last *': 'Heartbeat age'}}}},
    ]
    spec['vizConfig']['spec']['fieldConfig']['overrides'] = [{
        'matcher': {'id': 'byName', 'options': 'Heartbeat age'},
        'properties': [
            {'id': 'unit', 'value': 's'},
            {'id': 'custom.cellOptions', 'value': {'type': 'color-text'}},
            {'id': 'thresholds', 'value': {'mode': 'absolute', 'steps': [
                {'value': None, 'color': 'green'}, {'value': 180, 'color': 'orange'},
                {'value': 300, 'color': 'red'}]}},
        ],
    }]
    return table


def dashboard(api, uid, title, panels):
    return {'apiVersion': 'dashboard.grafana.app/v2', 'kind': 'Dashboard',
            'metadata': {'name': uid, 'annotations': {api.FOLDER_ANNOTATION: FOLDER}},
            'spec': {'title': title, 'description': 'Customer monitoring; navigation is managed automatically.',
                     'tags': [api.OWNER, 'customers'], 'editable': False, 'annotations': [],
                     'cursorSync': 'Off', 'links': [], 'variables': [], 'liveNow': False, 'preload': False,
                     'timeSettings': {'from': 'now-5m', 'to': 'now', 'autoRefresh': '30s'},
                     'elements': {'panel-' + str(p['spec']['id']): p for p in panels},
                     'layout': {'kind': 'AutoGridLayout', 'spec': {'maxColumnCount': 3,
                         'columnWidthMode': 'standard', 'rowHeightMode': 'standard', 'items': [
                             {'kind': 'AutoGridLayoutItem', 'spec': {'element': {
                                 'kind': 'ElementReference', 'name': 'panel-' + str(p['spec']['id'])}}} for p in panels]}}}}


def shared_device(api, template, customers, datasource):
    first = customers[0]
    desired = api.render(template, {'hostid': '1', 'host': 'Choose a device', 'name': 'Choose a device'}, first['group'], datasource)
    desired['metadata']['name'] = DEVICE
    desired['metadata']['annotations'][api.FOLDER_ANNOTATION] = FOLDER
    spec = desired['spec']
    spec['title'] = 'Device details'
    spec['description'] = 'Choose customer and device. OS is shown in the Operating System panel.'
    spec['tags'] = [api.OWNER, 'customers']
    spec['editable'] = False
    spec['links'] = [{'title': 'Customers', 'type': 'link', 'url': link(OVERVIEW), 'asDropdown': False,
                      'includeVars': False, 'keepTime': False, 'targetBlank': False,
                      'icon': 'external link', 'tooltip': '', 'tags': []},
                     {'title': 'Service and website checks', 'type': 'link', 'url': link(CHECKS), 'asDropdown': False,
                      'includeVars': True, 'keepTime': True, 'targetBlank': False,
                      'icon': 'external link', 'tooltip': '', 'tags': []}]
    groups = '/^(' + '|'.join(re.escape(c['group']).replace('/', r'\/') for c in customers) + ')$/'
    for variable in spec['variables']:
        v = variable['spec']
        if v['name'] == 'Group':
            v['label'] = 'Customer'
            v['query']['spec']['group'] = groups
            v['refresh'] = 'onDashboardLoad'
        elif v['name'] == 'Host':
            v['current'] = {'text': '', 'value': ''}
            v['query']['spec'].update({'group': '$Group', 'host': '/.*/'})
            v['refresh'] = 'onDashboardLoad'
    # Shared OS-neutral metrics and compatible names for old/new template versions.
    filters = {'System Time': '/^(System Time|System Uptime)$/', 'CPU Load': 'CPU Utilization',
               'Active Download Speed': '/^Active Download Speed(:.*)?$/',
               'Active Upload Speed': '/^Active Upload Speed(:.*)?$/'}
    for element in spec['elements'].values():
        for entry in element['spec']['data']['spec']['queries']:
            q = entry['spec']['query']['spec']
            q['group']['filter'] = '$Group'
            q['host']['filter'] = '$Host'
            current = q.get('item', {}).get('filter')
            if current in filters:
                q['item']['filter'] = filters[current]
    spec['elements']['panel-3']['spec']['title'] = 'CPU Utilization (%)'
    spec['elements']['panel-3']['spec']['vizConfig']['spec']['fieldConfig']['defaults'].update({'unit': 'percent', 'min': 0, 'max': 100})
    # Arbitrary process lists are intentionally absent from the shared base view.
    spec['elements'].pop('panel-6', None)
    spec['layout']['spec']['items'] = [entry for entry in spec['layout']['spec']['items']
                                     if entry['spec']['element']['name'] != 'panel-6']
    os_query = query(template, datasource, first['group'], host='$Host', item='Operating System')
    os_query['spec']['group']['filter'] = '$Group'
    os_query['spec'].update({'queryType': '2', 'resultFormat': 'table'})
    spec['elements']['panel-os'] = panel(99, 'Operating system', 'table', os_query)
    spec['layout']['spec']['items'].insert(0, {'kind': 'AutoGridLayoutItem', 'spec': {'element': {'kind': 'ElementReference', 'name': 'panel-os'}}})
    age_query = query(template, datasource, first['group'], host='$Host', item='Agent data age')
    age_query['spec']['group']['filter'] = '$Group'
    spec['elements']['panel-age'] = panel(98, 'Agent data age', 'stat', age_query, age=True)
    spec['layout']['spec']['items'].insert(1, {'kind': 'AutoGridLayoutItem', 'spec': {'element': {'kind': 'ElementReference', 'name': 'panel-age'}}})
    return desired


def shared_checks(api, template, customers, datasource):
    desired = shared_device(api, template, customers, datasource)
    desired['metadata']['name'] = CHECKS
    spec = desired['spec']
    spec['title'] = 'Device — service and website checks'
    spec['description'] = 'Optional checks: configure required service/process lists or link Website availability. UNKNOWN can mean no profile or no data.'
    spec['links'][1].update({'title': 'Device details', 'url': link(DEVICE)})
    panels = []
    for number, title, item, missing_bad in [
            (1, 'Required Windows services', '/^Required service state:/', False),
            (2, 'Required processes', '/^Required process count:/', True),
            (3, 'Website failed step (0 = OK)', '/^Failed step of scenario/', False)]:
        q = query(template, datasource, customers[0]['group'], '$Host', item)
        q['spec']['group']['filter'] = '$Group'
        p = panel(number, title, 'stat', q)
        p['spec']['description'] = spec['description']
        p['spec']['data']['spec']['queryOptions'] = {'timeFrom': '5m'}
        v = p['spec']['vizConfig']['spec']
        v['options']['textMode'] = 'value_and_name'
        v['fieldConfig']['defaults']['thresholds'] = {'mode': 'absolute', 'steps': [
            {'value': None, 'color': 'red' if missing_bad else 'green'},
            {'value': 1, 'color': 'green' if missing_bad else 'red'}]}
        if not missing_bad:
            v['fieldConfig']['defaults']['mappings'].append(
                {'type': 'value', 'options': {'0': {'text': 'OK', 'color': 'green'}}})
        panels.append(p)
    q = query(template, datasource, customers[0]['group'], '$Host', 'Agent data age')
    q['spec']['group']['filter'] = '$Group'
    panels.append(panel(5, 'Agent data age', 'stat', q, age=True))
    q = query(template, datasource, customers[0]['group'], '$Host', '/^Response time for step/')
    q['spec']['group']['filter'] = '$Group'
    p = panel(4, 'Website response time', 'stat', q)
    v = p['spec']['vizConfig']['spec']['fieldConfig']['defaults']
    v['unit'] = 's'
    v['thresholds'] = {'mode': 'absolute', 'steps': [{'value': None, 'color': 'blue'}]}
    panels.append(p)
    layout = dashboard(api, CHECKS, spec['title'], panels)['spec']
    spec['elements'], spec['layout'] = layout['elements'], layout['layout']
    return desired


def shared_hardware(api, template, customers, datasource):
    desired = shared_device(api, template, customers, datasource)
    desired['metadata']['name'] = HARDWARE
    spec = desired['spec']
    spec['title'] = 'Device — iDRAC and iLO hardware'
    spec['description'] = 'Official Dell/HPE templates required. Health values use vendor mappings. Sensor samples may be retained unchanged for hours; check SNMP availability and active problems separately.'
    spec['links'] = spec['links'][:1]
    spec['timeSettings'].update({'from': 'now-24h', 'autoRefresh': '30s'})
    panels = []
    for number, title, item in [
            (1, 'SNMP agent availability', 'SNMP agent availability'),
            (2, 'Overall hardware health — last known', 'Overall system health status'),
            (3, 'Storage and controller health — last known', '/([Dd]isk|[Cc]ontroller|RAID).*(status|Status|condition|Condition)$/'),
            (4, 'Power and fan health — last known', '/([Pp]ower|PSU|[Ff]an).*(status|Status|condition|Condition)$/')]:
        q = query(template, datasource, customers[0]['group'], '$Host', item)
        q['spec']['group']['filter'] = '$Group'
        q['spec']['options']['useZabbixValueMapping'] = True
        p = panel(number, title, 'stat' if number == 1 else 'table', q)
        p['spec']['description'] = spec['description']
        p['spec']['vizConfig']['spec']['fieldConfig']['defaults']['color'] = {'mode': 'fixed', 'fixedColor': 'blue'}
        if number == 1:
            p['spec']['data']['spec']['queryOptions'] = {'timeFrom': '5m'}
            v = p['spec']['vizConfig']['spec']['fieldConfig']['defaults']
            v['thresholds'] = {'mode': 'absolute', 'steps': [{'value': None, 'color': 'gray'}]}
            v['mappings'].append({'type': 'value', 'options': {
                '0': {'text': 'UNAVAILABLE', 'color': 'red'},
                '1': {'text': 'AVAILABLE', 'color': 'green'},
                '2': {'text': 'UNKNOWN', 'color': 'gray'}}})
        panels.append(p)
    q = query(template, datasource, customers[0]['group'], '$Host', problems=True)
    q['spec']['group']['filter'] = '$Group'
    panels.append(panel(5, 'Active hardware problems', 'table', q))
    for number, title, item, unit in [
            (6, 'Temperature sensors', '/: Temperature$/', 'celsius'),
            (7, 'Fan speed', '/[Ff]an.*: [Ss]peed$/', 'rotrpm')]:
        q = query(template, datasource, customers[0]['group'], '$Host', item)
        q['spec']['group']['filter'] = '$Group'
        p = panel(number, title, 'timeseries', q)
        p['spec']['vizConfig']['spec']['fieldConfig']['defaults'].update(
            {'unit': unit, 'color': {'mode': 'palette-classic'}})
        p['spec']['description'] = spec['description']
        panels.append(p)
    layout = dashboard(api, HARDWARE, spec['title'], panels)['spec']
    spec['elements'], spec['layout'] = layout['elements'], layout['layout']
    return desired


def sync_customers(api, zabbix, grafana, template, customers, datasource):
    source = grafana.request('GET', '/api/datasources/uid/' + datasource)
    if source.get('type') != 'alexanderzobnin-zabbix-datasource':
        raise ValueError('Configured datasource must be a Zabbix datasource')
    groups = zabbix.rpc('hostgroup.get', {'output': ['groupid', 'name'], 'filter': {'name': [c['group'] for c in customers]}})
    if {g['name'] for g in groups} != {c['group'] for c in customers}:
        raise RuntimeError('A configured customer group is absent or inaccessible; dashboards left unchanged')
    hosts = zabbix.rpc('host.get', {'output': ['hostid', 'host', 'name', 'proxyid', 'monitored_by'],
        'groupids': [g['groupid'] for g in groups], 'selectHostGroups': ['groupid', 'name'],
        'selectParentTemplates': ['host', 'name'], 'selectInventory': ['os', 'os_full', 'os_short'],
        'filter': {'status': '0'}})
    by_group = {c['group']: [] for c in customers}
    seen = set()
    for host in hosts:
        memberships = [g['name'] for g in host.get('hostgroups', []) if g['name'] in by_group]
        if len(memberships) != 1:
            raise ValueError('Each monitored device must belong to exactly one configured customer group')
        if host['hostid'] in seen:
            continue
        seen.add(host['hostid'])
        by_group[memberships[0]].append(host)
    desired = [shared_device(api, template, customers, datasource), shared_checks(api, template, customers, datasource),
               shared_hardware(api, template, customers, datasource)]
    roster = ['| Customer | Proxy | Public location |', '| --- | --- | --- |']
    for customer in customers:
        name = markdown(customer['name'])
        uid = 'zbx-customer-' + customer['id']
        location = markdown(customer.get('location', '—'))
        roster.append(f"| [{name}]({link(uid)}) | {markdown(customer['proxy'])} | {location} |")
    overview = [
        panel(1, 'Customers', 'text', content='\n'.join(roster)),
        proxy_age_table(template, customers, datasource),
    ]
    for i, customer in enumerate(customers, 1):
        uid = 'zbx-customer-' + customer['id']
        devices = sorted(by_group[customer['group']], key=lambda h: (h.get('name') or h['host']).casefold())
        navigation = ['[All customers](' + link(OVERVIEW) + ')', '',
                      '**Proxy:** ' + markdown(customer['proxy']), '',
                      '**Monitored devices:** ' + str(len(devices)), '']
        for host in devices:
            name = host.get('name') or host['host']
            view, label = device_view(host)
            navigation.append('- [' + markdown(name) + '](' + link(view, Group=customer['group'], Host=name) + ') — ' + (label or api.host_os(host, customer['group'])))
        if not devices:
            navigation.append('No enabled devices in this customer group; health is unknown.')
        if len({h.get('name') or h['host'] for h in devices}) != len(devices):
            raise ValueError('Device display names must be unique within each customer for unambiguous links')
        proxy_query = query(template, datasource, 'Monitoring/Proxies', exact(customer['proxy_host']), 'Proxy heartbeat age')
        panels = [panel(1, customer['name'] + ' — devices', 'text', content='\n'.join(navigation)),
                  panel(2, 'Proxy heartbeat age', 'stat', proxy_query, age=True),
                  panel(3, 'Active problems', 'table', query(template, datasource, customer['group'], problems=True))]
        for number, host in enumerate(devices, 4):
            name = host.get('name') or host['host']
            view, label = device_view(host)
            if view != DEVICE:
                continue
            panels.append(panel(number, name + ' — ' + api.host_os(host, customer['group']) + ' — data age',
                                'stat', query(template, datasource, customer['group'], exact(name), 'Agent data age'),
                                url=link(DEVICE, Group=customer['group'], Host=name), age=True))
        desired.append(dashboard(api, uid, customer['name'], panels))
        overview.append(panel(i * 3, customer['name'] + ' — active problems (' + str(len(devices)) + ' devices)', 'stat',
                              query(template, datasource, customer['group'], problems=True, count=True), url=link(uid)))
        overview.append(panel(i * 3 + 1, customer['name'] + ' — critical problems', 'stat',
                              query(template, datasource, customer['group'], problems=True, count=True, min_severity=4),
                              url=link(uid), critical=True))
    desired.append(dashboard(api, OVERVIEW, 'Customers — overview', overview))
    # Plan all resources and validate before the first write. No snapshots of live status are embedded.
    folders = grafana.request('GET', '/api/search?type=dash-folder&query=Zabbix%20Customers')
    folder = next((f for f in folders if f.get('uid') == FOLDER), None)
    if folder and folder.get('title') != 'Zabbix Customers':
        raise RuntimeError('Customer folder UID belongs to another folder')
    if folder is None:
        grafana.request('POST', '/api/folders', {'uid': FOLDER, 'title': 'Zabbix Customers'})
    changed = sum(api.upsert(grafana, DASHBOARDS, resource) for resource in desired)
    api.LOG.info('Synced %d customers, %d devices; %d resources changed', len(customers), len(seen), changed)
    return changed
