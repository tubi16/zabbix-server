#!/usr/bin/env python3
"""Interactive bootstrap for tubi16/zabbix-server and tubi16/zabbix-agent."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request


def run(*args, cwd=None, root=False):
    command = list(map(str, args))
    if root and os.geteuid() != 0:
        command.insert(0, "sudo")
    print("+", shlex.join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def ask(message):
    return input(message + " [e/H]: ").strip().lower() in {"e", "evet"}


def release():
    data = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            data[key] = value.strip('"\'')
    if data.get('ID') not in {'ubuntu', 'debian', 'arch'}:
        raise SystemExit('Desteklenen sistemler: Ubuntu, Debian, Arch Linux.')
    return data


def packages(distro, names):
    if not ask('Paket kurulacak: ' + ', '.join(names) + '. Devam edilsin mi?'):
        raise SystemExit('Paket kurulumu iptal edildi.')
    if distro == 'arch':
        run('pacman', '-S', '--needed', *names, root=True)
    else:
        run('apt-get', 'update', root=True)
        run('apt-get', 'install', *names, root=True)


def checkout(kind, base, distro):
    if not shutil.which('git'):
        packages(distro, ['git'])
    target = base / ('staj-' + kind)
    url = 'https://github.com/tubi16/zabbix-' + kind + '.git'
    if target.exists():
        if target.is_symlink() or not (target / '.git').is_dir():
            raise SystemExit('Hedef mevcut fakat bağımsız Git reposu değil: ' + str(target))
        origin = subprocess.check_output(['git', '-C', str(target), 'remote', 'get-url', 'origin'], text=True).strip()
        accepted = {url, url[:-4], 'git@github.com:tubi16/zabbix-' + kind + '.git'}
        if origin not in accepted:
            raise SystemExit('Mevcut reponun origin adresi beklenen repo ile eşleşmiyor.')
        print('Mevcut repo kullanılacak; yerel değişiklikler korunur, otomatik pull yapılmaz.')
    else:
        base.mkdir(parents=True, exist_ok=True)
        run('git', 'clone', '--', url, target)
    required = 'scripts/prepare_config.py' if kind == 'server' else 'install.py'
    if not (target / required).is_file():
        raise SystemExit('Gerekli dosya eksik: ' + required)
    return target


def server(target, distro):
    has_docker = bool(shutil.which('docker'))
    has_compose = has_docker and subprocess.run(['docker', 'compose', 'version'], capture_output=True).returncode == 0
    if not has_compose:
        if distro == 'arch':
            packages(distro, ['docker', 'docker-compose'])
        else:
            # Use an available distro package; never replace an existing engine.
            run('apt-get', 'update', root=True)
            compose = None
            for name in ('docker-compose-v2', 'docker-compose-plugin', 'docker-compose'):
                result = subprocess.run(['apt-cache', 'policy', name], capture_output=True, text=True, check=True, env={**os.environ, 'LC_ALL': 'C'})
                match = re.search(r'Candidate:\s+(\S+)', result.stdout)
                if match and match[1] != '(none)' and (name != 'docker-compose' or re.match(r'(?:\d+:)?[2-9]\.', match[1])):
                    compose = name
                    break
            if not compose:
                raise SystemExit('Compose v2 paketi bulunamadı. Docker resmi kurulumunu tamamlayıp tekrar çalıştır: https://docs.docker.com/engine/install/')
            packages(distro, ([ ] if has_docker else ['docker.io']) + [compose])
    run('docker', 'compose', 'version', root=True)
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'docker']).returncode != 0:
        if not ask('Docker servisi başlatılsın mı?'):
            raise SystemExit('Docker çalışır durumda olmalı.')
        run('systemctl', 'start', 'docker', root=True)
    run('docker', 'info', root=True)
    run(sys.executable, target / 'scripts/prepare_config.py')
    run('docker', 'compose', 'config', '--quiet', cwd=target, root=True)
    print('Ayarlar hazır. Port ve ağları .env içinde kontrol et. Parolalar ekrana yazılmaz.')
    if ask('Bu projenin servisleri docker compose up -d ile başlatılsın mı?'):
        run('docker', 'compose', 'up', '-d', cwd=target, root=True)
        run('docker', 'compose', 'ps', cwd=target, root=True)
    print('Devam: ' + str(target / 'docs/kurulum.md'))
    print('Durdurma (veri korunur): cd ' + shlex.quote(str(target)) + ' && sudo docker compose stop')


def install_agent(info):
    distro = info['ID']
    if shutil.which('zabbix_agent2'):
        return 'agent2'
    if shutil.which('zabbix_agentd'):
        return 'classic'
    if distro != 'arch':
        version = info.get('VERSION_ID', '')
        if not re.fullmatch(r'\d+(?:\.\d+)?', version):
            raise SystemExit('Dağıtım sürümü belirlenemedi.')
        url = (f'https://repo.zabbix.com/zabbix/7.4/release/{distro}/pool/main/z/zabbix-release/'
               f'zabbix-release_latest_7.4+{distro}{version}_all.deb')
        if not ask('Resmi Zabbix 7.4 paket deposu eklensin mi? Diğer Zabbix paketlerinin aday sürümleri de değişebilir.'):
            raise SystemExit('Depo kurulumu iptal edildi.')
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'zabbix-release.deb'
            urllib.request.urlretrieve(url, archive)
            archive.chmod(0o644)
            Path(temp).chmod(0o755)
            run('dpkg', '-i', archive, root=True)
    packages(distro, ['zabbix-agent2'])
    return 'agent2'


def agent(target, info):
    print('Paket yöneticisi kurulum sırasında agent servisini başlatabilir.')
    choice = install_agent(info)
    if not ask('Mevcut PSK dosyasıyla TLS yapılandırılsın mı? Agent servisi yeniden başlatılır.'):
        print('Paket hazır. Host kaydı ve TLS için sunucu reposunda zabbix/tls/enroll.py kullan.')
        return
    host = input('Zabbix teknik host adı: ').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', host):
        raise SystemExit('Geçersiz host adı.')
    key = Path(input('PSK dosya yolu (anahtarın kendisini yazma): ').strip()).expanduser().resolve()
    if not key.is_file() or not re.fullmatch(r'[0-9a-fA-F]{64}', key.read_text().strip()):
        raise SystemExit('PSK dosyası 64 hexadecimal karakter içermeli.')
    sources = input('İzinli sunucu IP/alt ağları (virgülle): ').strip().split(',')
    command = [sys.executable, target / 'install.py', '--host', host, '--key', key, '--agent', choice, '--strict']
    for source in sources:
        ipaddress.ip_network(source.strip(), strict=False)
        command.extend(['--server', source.strip()])
    print('Strict TLS uygulanacak. Sunucuda aynı host/PSK kimliği ayrıca kayıtlı olmalı.')
    if ask('Agent config yedeği alınarak TLS uygulansın mı?'):
        run(*command, root=True)
        print('Geri alma: install.py çıktısındaki yedek ve komutu kullan; sunucu TLS ayarını da eşleştir.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path.home() / 'zabbix-project', help='Repoların üst dizini')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('Normal kullanıcıyla çalıştır; gerekli komutlarda sudo sorulur.')
    if not sys.stdin.isatty():
        raise SystemExit('Etkileşimli terminal gerekli; önce dosyayı indir, sonra python3 setup.py çalıştır.')
    info = release()
    selection = input('Kurulum: 1) Server  2) Agent: ').strip()
    if selection not in {'1', '2'}:
        raise SystemExit('1 veya 2 seçilmeli.')
    kind = 'server' if selection == '1' else 'agent'
    target = checkout(kind, args.directory.expanduser().resolve(), info['ID'])
    if kind == 'server':
        server(target, info['ID'])
    else:
        agent(target, info)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit('Kurulum durduruldu: ' + str(error))
    except (KeyboardInterrupt, EOFError):
        sys.exit('Kurulum iptal edildi; tamamlanan adımlar geri alınmadı.')
