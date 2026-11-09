"""Generate fresh local credentials without copying live secrets."""
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def write_private(path, value, mode=0o600):
    if path.exists():
        return False
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "w") as file:
        file.write(value)
    return True


def main():
    content = (ROOT / ".env.example").read_text()
    content = content.replace("GF_SECURITY_ADMIN_PASSWORD=\n",
                              "GF_SECURITY_ADMIN_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
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
    print("Configure Zabbix datasource credentials and API tokens in .env before enabling host-sync.")


if __name__ == "__main__":
    main()
