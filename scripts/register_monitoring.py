"""Create a new PSK-only active proxy or active-agent host using the local API."""
import argparse
from pathlib import Path
import re
import sys

from bootstrap_admin import logout, read_env, rpc


def registration(args, call=rpc):
    if args.key.is_symlink() or args.key.stat().st_mode & 0o077:
        raise ValueError('PSK dosyası sembolik bağlantı olmamalı; izinlerini chmod 600 ile ayarla.')
    key = args.key.read_text().strip()
    if not re.fullmatch(r'[0-9a-fA-F]{64}', key):
        raise ValueError('PSK dosyası 64 hexadecimal karakter içermeli.')
    password = read_env().get('ZABBIX_ADMIN_PASSWORD', '')
    if not password:
        raise ValueError('Yerel .env içinde ZABBIX_ADMIN_PASSWORD gerekli.')
    session = call('user.login', {'username': 'Admin', 'password': password})
    try:
        kind = args.kind
        field = 'name' if kind == 'proxy' else 'host'
        existing = call(kind + '.get', {'output': [kind + 'id'], 'filter': {field: [args.name]}}, session)
        if existing:
            raise ValueError('Bu isimde kayıt mevcut; değiştirilmedi. Mevcut kayıt geçişini web arayüzünde yap.')
        params = {field: args.name, 'tls_accept': 2,
                  'tls_psk_identity': args.identity or
                  (args.name + '-server' if kind == 'proxy' else 'staj-' + args.name),
                  'tls_psk': key}
        if kind == 'proxy':
            # No fixed allowed_addresses: a remote site's public NAT address can change.
            params['operating_mode'] = 0
        else:
            proxies = call('proxy.get', {'output': ['proxyid'], 'filter': {'name': [args.proxy]}}, session)
            templates = call('template.get', {'output': ['templateid'],
                                             'filter': {'host': ['Essential Items Active']}}, session)
            if len(proxies) != 1 or len(templates) != 1:
                raise ValueError('Proxy kaydı veya Essential Items Active template bulunamadı.')
            groups = call('hostgroup.get', {'output': ['groupid'], 'filter': {'name': [args.group]}}, session)
            if not groups:
                raise ValueError('Host grubu yok; web arayüzünde önce grubu oluştur: ' + args.group)
            params.update({'monitored_by': 1, 'proxyid': proxies[0]['proxyid'],
                           'tls_connect': 2, 'groups': groups, 'templates': templates})
        print(f"Plan: yeni {kind} kaydı '{args.name}', yalnızca TLS-PSK.")
        if args.apply:
            result = call(kind + '.create', params, session)
            if not result.get(kind + 'ids'):
                raise RuntimeError('API kayıt doğrulaması başarısız.')
            print('Kayıt oluşturuldu. PSK gösterilmedi.')
        else:
            print('Değişiklik yapılmadı; uygulamak için --apply ekle.')
    finally:
        logout(session, call)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['proxy', 'host'])
    parser.add_argument('--name', required=True)
    parser.add_argument('--key', required=True, type=Path)
    parser.add_argument('--identity')
    parser.add_argument('--proxy', help='Hostun atanacağı proxy adı')
    parser.add_argument('--group', default='Linux servers')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.name):
        parser.error('İsim 1–64 ASCII harf/rakam, nokta, alt çizgi veya tire olmalı.')
    if args.kind == 'host' and not args.proxy:
        parser.error('Host kaydı için --proxy gerekli.')
    registration(args)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error) if isinstance(error, (ValueError, RuntimeError)) else
              'Kayıt başarısız; yerel dosya izinlerini ve API erişimini kontrol et.', file=sys.stderr)
        sys.exit(1)
