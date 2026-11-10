"""Import the bundled Essential Items template without deleting existing objects."""
from pathlib import Path
import sys
import argparse
import re
import uuid

from bootstrap_admin import logout, main as bootstrap_admin, read_env, rpc


TEMPLATE = Path(__file__).resolve().parents[1] / 'zabbix/templates/essential-items.yaml'


def active_source(source):
    """Give the active variant separate, deterministic UUIDs; retain dependent items."""
    head, body = source.split('  templates:\n', 1)
    body = body.replace("'Essential Items'", "'Essential Items Active'")
    body = body.replace('/Essential Items/', '/Essential Items Active/')
    body = re.sub(r'(?m)^(\s*(?:- )?uuid: )([0-9a-f]{32})$',
                  lambda m: m[1] + uuid.UUID(bytes=uuid.uuid5(uuid.NAMESPACE_URL,
                                                            'zabbix-essential-active/' + m[2]).bytes,
                                             version=4).hex, body)
    lines = body.splitlines(keepends=True)
    result = []
    for index, line in enumerate(lines):
        result.append(line)
        match = re.match(r'^( {8}| {12})- uuid:', line)
        if not match:
            continue
        indent = len(match[1])
        block = []
        for following in lines[index + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            block.append(following)
        if (any(re.match(r'^ {' + str(indent + 2) + r'}key:', item) for item in block)
                and not any(re.match(r'^ {' + str(indent + 2) + r'}type:', item) for item in block)):
            result.append(' ' * (indent + 2) + 'type: ZABBIX_ACTIVE\n')
    return head + '  templates:\n' + ''.join(result)


def import_template(call=rpc, active=False):
    source = TEMPLATE.read_text()
    template_name = 'Essential Items Active' if active else 'Essential Items'
    if active:
        source = active_source(source)
    password = read_env().get('ZABBIX_ADMIN_PASSWORD', '')
    if not password.strip():
        raise RuntimeError('Set ZABBIX_ADMIN_PASSWORD in .env first.')
    session = call('user.login', {'username': 'Admin', 'password': password})
    try:
        rules = {'template_groups': {'createMissing': True},
                 'templates': {'createMissing': True, 'updateExisting': True}}
        for name in ('items', 'discoveryRules', 'triggers', 'valueMaps'):
            rules[name] = {'createMissing': True, 'updateExisting': True,
                           'deleteMissing': False}
        if call('configuration.import', {'format': 'yaml', 'source': source,
                                         'rules': rules}, session) is not True:
            raise RuntimeError('Template import did not succeed.')
        templates = call('template.get', {'output': ['templateid'],
                         'filter': {'host': [template_name]}}, session)
        if len(templates) != 1:
            raise RuntimeError('Essential Items template verification failed.')
    finally:
        logout(session, call)
    print(template_name + ' imported and verified; no missing objects deleted.')


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--active', action='store_true', help='Import the separate active-agent variant')
        args = parser.parse_args()
        bootstrap_admin()
        import_template(active=args.active)
    except (RuntimeError, OSError, ValueError) as error:
        print(str(error) if isinstance(error, RuntimeError) else
              'Template setup failed; check local configuration/API connectivity.', file=sys.stderr)
        sys.exit(1)
