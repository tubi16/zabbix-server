"""Store tokens locally without terminal echo or shell history."""
from getpass import getpass
import os
from pathlib import Path

directory = Path(__file__).parent / "secrets"
directory.mkdir(mode=0o700, exist_ok=True)
directory.chmod(0o700)
for name, label in (("grafana_token", "Grafana service account token"),
                    ("zabbix_token", "Zabbix API token")):
    path = directory / name
    if path.exists() and path.stat().st_size:
        print(f"{name} already exists; kept unchanged")
        continue
    token = getpass(label + ": ").strip()
    if not token:
        raise SystemExit("Empty token; not saved")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(token + "\n")
    print(f"{name} saved")
