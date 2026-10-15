#!/usr/bin/env python3
"""Create and validate the ignored local Compose environment (stdlib only)."""

import os
import re
import secrets
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
LOCAL = ROOT / ".env"
SECRET_KEYS = ("POSTGRES_PASSWORD", "N8N_DB_PASSWORD", "N8N_ENCRYPTION_KEY")
REQUIRED = (
    "COMPOSE_PROJECT_NAME",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "N8N_DB_NAME",
    "N8N_DB_USER",
    "N8N_DB_PASSWORD",
    "N8N_HOST",
    "N8N_PORT",
    "N8N_PROTOCOL",
    "N8N_ENCRYPTION_KEY",
    "N8N_WEBHOOK_URL",
    "GENERIC_TIMEZONE",
)


def parse_env(path):
    values = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path.name}:{number}: expected KEY=value")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ValueError(f"{path.name}:{number}: invalid or duplicate key")
        values[key] = value
    return values


def validate(values):
    missing = [key for key in REQUIRED if not values.get(key)]
    if missing:
        raise ValueError("missing required settings: " + ", ".join(missing))
    for key in SECRET_KEYS:
        value = values[key]
        if len(value) < 32 or value == "GENERATE_LOCAL_SECRET":
            raise ValueError(f"{key} must be a unique random value of at least 32 characters")
    if len({values[key] for key in SECRET_KEYS}) != len(SECRET_KEYS):
        raise ValueError("local secrets must be distinct")
    for key in ("POSTGRES_DB", "POSTGRES_USER", "N8N_DB_NAME", "N8N_DB_USER"):
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", values[key]):
            raise ValueError(f"{key} must be a lowercase PostgreSQL identifier")
    if values["POSTGRES_DB"] == values["N8N_DB_NAME"]:
        raise ValueError("application and n8n database names must differ")
    if values["POSTGRES_USER"] == values["N8N_DB_USER"]:
        raise ValueError("application and n8n database users must differ")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", values["COMPOSE_PROJECT_NAME"]):
        raise ValueError("COMPOSE_PROJECT_NAME contains invalid characters")
    for key in ("POSTGRES_PORT", "N8N_PORT"):
        if not values[key].isdigit() or not 1 <= int(values[key]) <= 65535:
            raise ValueError(f"{key} must be a valid TCP port")
    if values["POSTGRES_PORT"] == values["N8N_PORT"]:
        raise ValueError("PostgreSQL and n8n host ports must differ")
    if values["N8N_HOST"] != "localhost" or values["N8N_PROTOCOL"] != "http":
        raise ValueError("M1 permits only localhost HTTP n8n access")
    expected_url = f"http://localhost:{values['N8N_PORT']}/"
    if values["N8N_WEBHOOK_URL"] != expected_url:
        raise ValueError(f"N8N_WEBHOOK_URL must be {expected_url}")


def init():
    if LOCAL.exists():
        raise ValueError(".env already exists; it was not overwritten")
    content = EXAMPLE.read_text(encoding="utf-8")
    for _ in SECRET_KEYS:
        content = content.replace("GENERATE_LOCAL_SECRET", secrets.token_hex(32), 1)
    values = parse_env_text(content)
    validate(values)
    descriptor = os.open(str(LOCAL), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)
    print("Created ignored .env with unique local secrets (permissions 0600).")


def parse_env_text(content):
    values = {}
    for line in content.splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def check():
    if not LOCAL.is_file():
        raise ValueError(".env is missing; run `make init`")
    validate(parse_env(LOCAL))
    print("Local environment is valid (secret values hidden).")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ("init", "check"):
            raise ValueError("usage: python3 scripts/local_env.py {init|check}")
        (init if sys.argv[1] == "init" else check)()
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
