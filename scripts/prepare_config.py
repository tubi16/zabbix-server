"""Generate fresh local credentials without copying live secrets."""
import argparse
import os
from pathlib import Path
import secrets
import re

ROOT = Path(__file__).resolve().parents[1]


def write_private(path, value, mode=0o600):
    if path.is_symlink():
        raise ValueError('Refusing a symlink: ' + str(path))
    if path.exists():
        return False
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "w") as file:
        file.write(value)
    return True


def ask_port(label, default):
    while True:
        value = input(f'{label} [{default}]: ').strip() or str(default)
        if value.isascii() and value.isdecimal() and 1024 <= int(value) <= 65535:
            return str(int(value))
        print('1024–65535 arasında bir port gir.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive', action='store_true', help='Yeni kurulum portlarını sor')
    parser.add_argument('--production', action='store_true', help='Sabit image sürümleri ve yalnızca yerel yönetim portları')
    args = parser.parse_args()
    content = (ROOT / ".env.example").read_text()
    env = ROOT / '.env'
    if args.production:
        if not args.interactive and not env.exists():
            parser.error('Yeni üretim kurulumu için --interactive gerekli.')
        if env.exists():
            values = dict(line.split('=', 1) for line in env.read_text().splitlines()
                          if line and not line.startswith('#') and '=' in line)
            if (not re.fullmatch(r'alpine-7\.4\.\d+', values.get('ZBX_IMAGE_TAG', ''))
                    or not re.fullmatch(r'\d+\.\d+\.\d+', values.get('GRAFANA_IMAGE_TAG', ''))
                    or not re.fullmatch(r'8\.4\.\d+(?:-oracle)?', values.get('MYSQL_IMAGE_TAG', ''))
                    or values.get('ZABBIX_WEB_BIND_IP') != '127.0.0.1'
                    or values.get('GRAFANA_BIND_IP') != '127.0.0.1'):
                parser.error('Mevcut .env değişmedi. Üretim için ZBX_IMAGE_TAG=alpine-7.4.X, GRAFANA_IMAGE_TAG=X.Y.Z, MYSQL_IMAGE_TAG=8.4.X, ZABBIX_WEB_BIND_IP=127.0.0.1, GRAFANA_BIND_IP=127.0.0.1 ayarla. Önce DB yedeği al.')
        else:
            for key, label, pattern in (
                ('ZBX_IMAGE_TAG', 'Onayladığın Zabbix etiketi (alpine-7.4.X)', r'alpine-7\.4\.\d+'),
                ('GRAFANA_IMAGE_TAG', 'Onayladığın Grafana sürümü (X.Y.Z)', r'\d+\.\d+\.\d+'),
                ('MYSQL_IMAGE_TAG', 'Onayladığın MySQL etiketi (8.4.X)', r'8\.4\.\d+(?:-oracle)?'),
            ):
                while True:
                    value = input(label + ': ').strip()
                    if re.fullmatch(pattern, value):
                        break
                    print('Tam patch sürümü gir; latest/kayan etiket kabul edilmez.')
                if re.search(r'(?m)^' + key + '=', content):
                    content = re.sub(r'(?m)^' + key + '=.*$', key + '=' + value, content)
                else:
                    content += '\n' + key + '=' + value + '\n'
            content += '\nZABBIX_WEB_BIND_IP=127.0.0.1\nGRAFANA_BIND_IP=127.0.0.1\n'
    if args.interactive and not (ROOT / '.env').exists():
        used = set()
        for key, label, default in (
            ('ZABBIX_WEB_NGINX_HTTP_PORT', 'Zabbix web portu', 8080),
            ('GRAFANA_PORT', 'Grafana web portu', 3001),
            ('ZABBIX_SERVER_PORT', 'Zabbix server portu', 10081),
        ):
            while True:
                port = ask_port(label, default)
                if port not in used:
                    used.add(port)
                    break
                print('Bu port başka bir kurulum yanıtında kullanıldı.')
            content = content.replace(f'{key}={default}\n', f'{key}={port}\n')
    elif args.interactive:
        print('Mevcut .env korunuyor; portlar değiştirilmedi.')
    content = content.replace("GF_SECURITY_ADMIN_PASSWORD=\n",
                              "GF_SECURITY_ADMIN_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
    content = content.replace("ZABBIX_ADMIN_PASSWORD=\n",
                              "ZABBIX_ADMIN_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
    write_private(ROOT / ".env", content)
    # Compose secrets are bind mounts: non-root Zabbix must read the mounted
    # files. The parent directory stays private on the host.
    (ROOT / "env_vars").chmod(0o700)
    for name, value in {
        ".MYSQL_USER": "zabbix", ".MYSQL_ROOT_USER": "root",
        ".MYSQL_PASSWORD": secrets.token_urlsafe(32),
        ".MYSQL_ROOT_PASSWORD": secrets.token_urlsafe(32),
        ".POSTGRES_USER": "zabbix", ".POSTGRES_PASSWORD": secrets.token_urlsafe(32),
    }.items():
        write_private(ROOT / "env_vars" / name, value + "\n", mode=0o644)
    print("Local .env and database credentials prepared; existing files kept unchanged.")
    print("Zabbix datasource defaults to the generated Admin password; configure API tokens before enabling host-sync.")


if __name__ == "__main__":
    main()
