"""Shared validation, local credentials and Zabbix API access."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = Path(__file__).parent / "private"


def host_name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise argparse.ArgumentTypeError("Use 1–64 ASCII letters, digits, dots, underscores or hyphens")
    return value


def read_env():
    return dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                if line and not line.startswith("#") and "=" in line)


def ensure_key(host, directory=PRIVATE):
    host_name(host)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / (host + ".psk")
    if path.is_symlink():
        raise ValueError("Refusing a symlink as a PSK file")
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write(secrets.token_hex(32) + "\n")
    key = path.read_text().strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", key):
        raise ValueError("Invalid existing PSK; refusing to replace it")
    path.chmod(0o600)
    return path


def rpc(method, params, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    request = Request("http://127.0.0.1:8080/api_jsonrpc.php", data=body, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError("Zabbix HTTP " + str(error.code)) from None
    if "error" in result:
        # Never dump API request/response bodies containing passwords or PSKs.
        raise RuntimeError(method + " failed: " + str(result["error"].get("code")))
    return result["result"]
