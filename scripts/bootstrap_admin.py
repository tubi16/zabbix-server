"""Replace the factory Admin password with the local .env password."""
import argparse
import json
from pathlib import Path
import sys
import time
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'zabbix/tls'))
from psk_common import read_env, rpc


def logout(session, call):
    try:
        call('user.logout', [], session)
    except (RuntimeError, OSError, ValueError):
        pass


def bootstrap(call=rpc):
    password = read_env().get('ZABBIX_ADMIN_PASSWORD', '')
    if not password.strip() or password == 'zabbix':
        raise RuntimeError('Set a non-default ZABBIX_ADMIN_PASSWORD in .env first; existing .env files are never overwritten.')
    try:
        session = call('user.login', {'username': 'Admin', 'password': password})
    except RuntimeError:
        session = None
    if session:
        logout(session, call)
        print('Zabbix Admin already matches .env; no password changes.')
        return
    try:
        factory = call('user.login', {'username': 'Admin', 'password': 'zabbix', 'userData': True})
    except RuntimeError:
        raise RuntimeError('Neither .env nor factory login succeeded. Existing password was NOT reset. Check the account lock or update .env to the current Admin password.') from None
    session = factory['sessionid']
    try:
        call('user.update', {'userid': factory['userid'], 'passwd': password,
                             'current_passwd': 'zabbix'}, session)
    finally:
        logout(session, call)
    try:
        session = call('user.login', {'username': 'Admin', 'password': password})
    except RuntimeError:
        raise RuntimeError('Password update sent but verification failed. Do not retry default passwords; verify the .env password in the web UI.') from None
    logout(session, call)
    print('Zabbix Admin password updated from .env and verified; password not displayed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait', type=int, default=180, help='API startup timeout in seconds')
    args = parser.parse_args()
    if not 0 <= args.wait <= 600:
        parser.error('--wait must be 0–600')
    deadline = time.monotonic() + args.wait
    while True:
        try:
            rpc('apiinfo.version', {})
            break
        except (OSError, URLError, RuntimeError, json.JSONDecodeError):
            if time.monotonic() >= deadline:
                raise RuntimeError('Zabbix API is not ready; check ZABBIX_WEB_NGINX_HTTP_PORT in .env; no password changes.') from None
            time.sleep(min(2, max(0, deadline - time.monotonic())))
    bootstrap()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError):
        # API errors never contain request/response bodies; do not print secrets.
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, RuntimeError) else 'Admin setup failed; check local configuration/API connectivity.', file=sys.stderr)
        sys.exit(1)
