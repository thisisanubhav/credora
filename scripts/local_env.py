"""Create and validate the ignored local Compose environment (stdlib only)."""

import os
import re
import secrets
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
LOCAL = ROOT / ".env"
SECRET_KEYS = ("POSTGRES_PASSWORD", "N8N_DB_PASSWORD", "N8N_ENCRYPTION_KEY", "APP_DB_PASSWORD", "MATCHING_WEBHOOK_SECRET", "INTERNAL_STEP_SECRET")
REQUIRED = (
    "COMPOSE_PROJECT_NAME",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT",
    "APP_DB_USER",
    "APP_DB_PASSWORD",
    "TEST_DB_NAME",
    "N8N_DB_NAME",
    "N8N_DB_USER",
    "N8N_DB_PASSWORD",
    "N8N_HOST",
    "N8N_PORT",
    "N8N_PROTOCOL",
    "N8N_ENCRYPTION_KEY",
    "N8N_WEBHOOK_URL",
    "GENERIC_TIMEZONE",
    "LOCALSTACK_PORT", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION",
    "S3_ENDPOINT_URL", "S3_BUCKET", "CSV_MAX_BYTES", "CSV_CHUNK_SIZE",
    "UPLOAD_URL_TTL_SECONDS", "INGESTION_LEASE_SECONDS",
    "MATCHING_WEBHOOK_SECRET", "MATCHING_WEBHOOK_URL", "ALLOW_SYNTHETIC_DEMO",
    "INTERNAL_STEP_KEY_ID", "INTERNAL_STEP_SECRET",
    "NOTIFICATION_MODE", "NOTIFICATION_TRANSPORT", "NOTIFICATION_SES_ENABLED",
    "NOTIFICATION_TEST_EMAIL", "NOTIFICATION_FROM_EMAIL", "NOTIFICATION_WEBHOOK_URL",
    "FRONTEND_ORIGIN",
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
    for key in ("POSTGRES_DB", "POSTGRES_USER", "N8N_DB_NAME", "N8N_DB_USER", "APP_DB_USER", "TEST_DB_NAME"):
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", values[key]):
            raise ValueError(f"{key} must be a lowercase PostgreSQL identifier")
    if values["POSTGRES_DB"] == values["N8N_DB_NAME"]:
        raise ValueError("application and n8n database names must differ")
    if values["POSTGRES_USER"] == values["N8N_DB_USER"]:
        raise ValueError("application and n8n database users must differ")
    if len({values[key] for key in ("POSTGRES_DB", "N8N_DB_NAME", "TEST_DB_NAME")}) != 3:
        raise ValueError("test, application and n8n database names must differ")
    if len({values[key] for key in ("POSTGRES_USER", "N8N_DB_USER", "APP_DB_USER")}) != 3:
        raise ValueError("bootstrap, n8n and runtime database users must differ")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", values["COMPOSE_PROJECT_NAME"]):
        raise ValueError("COMPOSE_PROJECT_NAME contains invalid characters")
    for key in ("POSTGRES_PORT", "N8N_PORT", "LOCALSTACK_PORT"):
        if not values[key].isdigit() or not 1 <= int(values[key]) <= 65535:
            raise ValueError(f"{key} must be a valid TCP port")
    if len({values[key] for key in ("POSTGRES_PORT", "N8N_PORT", "LOCALSTACK_PORT")}) != 3:
        raise ValueError("local service ports must differ")
    if values["N8N_HOST"] != "localhost" or values["N8N_PROTOCOL"] != "http":
        raise ValueError("M1 permits only localhost HTTP n8n access")
    expected_url = f"http://localhost:{values['N8N_PORT']}/"
    if values["N8N_WEBHOOK_URL"] != expected_url:
        raise ValueError(f"N8N_WEBHOOK_URL must be {expected_url}")
    if values["MATCHING_WEBHOOK_URL"] != f"http://127.0.0.1:{values['N8N_PORT']}/webhook/loan-matching":
        raise ValueError("MATCHING_WEBHOOK_URL must point to the local matching webhook")
    if values["ALLOW_SYNTHETIC_DEMO"] not in {"0", "1"}:
        raise ValueError("ALLOW_SYNTHETIC_DEMO must be 0 or 1")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", values["INTERNAL_STEP_KEY_ID"]):
        raise ValueError("INTERNAL_STEP_KEY_ID is invalid")
    previous_id = values.get("INTERNAL_STEP_PREVIOUS_KEY_ID", "")
    previous_secret = values.get("INTERNAL_STEP_PREVIOUS_SECRET", "")
    if bool(previous_id) != bool(previous_secret):
        raise ValueError("previous internal key ID and secret must be configured together")
    if previous_id and (not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", previous_id)
                        or previous_id == values["INTERNAL_STEP_KEY_ID"]
                        or previous_secret == values["INTERNAL_STEP_SECRET"]
                        or len(previous_secret) < 32):
        raise ValueError("previous internal signing key is invalid")
    if values["NOTIFICATION_MODE"] != "test" or values["NOTIFICATION_TRANSPORT"] not in {"mock", "ses"}:
        raise ValueError("M6 permits test-only mock or SES transport")
    if values["NOTIFICATION_SES_ENABLED"] not in {"0", "1"}:
        raise ValueError("NOTIFICATION_SES_ENABLED must be 0 or 1")
    if values.get("NOTIFICATION_SES_MAX_ATTEMPTS", "0") not in {"0", "1"}:
        raise ValueError("NOTIFICATION_SES_MAX_ATTEMPTS must be 0 or 1")
    if values["NOTIFICATION_WEBHOOK_URL"] != f"http://127.0.0.1:{values['N8N_PORT']}/webhook/loan-notifications":
        raise ValueError("NOTIFICATION_WEBHOOK_URL must point to local n8n")
    if not re.fullmatch(r"http://(?:localhost|127\.0\.0\.1):[1-9][0-9]{0,4}", values["FRONTEND_ORIGIN"]):
        raise ValueError("FRONTEND_ORIGIN must be a loopback HTTP origin")
    for key in ("NOTIFICATION_TEST_EMAIL", "NOTIFICATION_FROM_EMAIL"):
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values[key]):
            raise ValueError(f"{key} must be an email address")
    if values["NOTIFICATION_TRANSPORT"] == "ses":
        if (values["NOTIFICATION_SES_ENABLED"] != "1" or
                values.get("NOTIFICATION_SES_MAX_ATTEMPTS") != "1" or
                any(values[key].endswith("@example.invalid") for key in
                    ("NOTIFICATION_TEST_EMAIL", "NOTIFICATION_FROM_EMAIL"))):
            raise ValueError("SES requires one-attempt enablement and non-placeholder verified identities")
        try:
            uuid.UUID(values.get("NOTIFICATION_SES_AUTHORIZED_BATCH_ID", ""))
        except ValueError as error:
            raise ValueError("SES requires a new authorized batch UUID") from error
        if not re.fullmatch(r"[0-9a-f]{64}", values.get("NOTIFICATION_SES_AUTHORIZED_IDEMPOTENCY_KEY", "")):
            raise ValueError("SES requires one authorized notification key")
    if values["S3_ENDPOINT_URL"] != f"http://127.0.0.1:{values['LOCALSTACK_PORT']}":
        raise ValueError("S3_ENDPOINT_URL must point to loopback LocalStack")
    for key in ("CSV_MAX_BYTES", "CSV_CHUNK_SIZE", "UPLOAD_URL_TTL_SECONDS", "INGESTION_LEASE_SECONDS"):
        if not values[key].isdigit() or int(values[key]) < 1:
            raise ValueError(f"{key} must be positive")


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


def extend():
    """Add only the new M2 settings to an existing M1 .env."""
    if not LOCAL.is_file():
        raise ValueError(".env is missing; run `make init`")
    values = parse_env(LOCAL)
    if all(key in values for key in ("APP_DB_USER", "APP_DB_PASSWORD", "TEST_DB_NAME")):
        validate(values)
        print("Local environment already has M2 settings (secret values hidden).")
        return
    additions = {
        "APP_DB_USER": "loan_engine_runtime",
        "APP_DB_PASSWORD": secrets.token_hex(32),
        "TEST_DB_NAME": "loan_engine_test",
    }
    additions = {key: value for key, value in additions.items() if key not in values}
    validate(values | additions)
    with LOCAL.open("a", encoding="utf-8") as output:
        for key, value in additions.items():
            output.write(f"{key}={value}\n")
    os.chmod(LOCAL, 0o600)
    print("Added missing M2 settings to ignored .env (secret values hidden).")


def extend_m3():
    """Append only emulator/ingestion settings to an existing ignored M2 environment."""
    if not LOCAL.is_file():
        raise ValueError(".env is missing; run `make init`")
    values = parse_env(LOCAL)
    template = parse_env(EXAMPLE)
    keys = ("LOCALSTACK_PORT", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION",
            "S3_ENDPOINT_URL", "S3_BUCKET", "CSV_MAX_BYTES", "CSV_CHUNK_SIZE",
            "UPLOAD_URL_TTL_SECONDS", "INGESTION_LEASE_SECONDS")
    additions = {key: template[key] for key in keys if key not in values}
    validate(values | additions)
    if additions:
        with LOCAL.open("a", encoding="utf-8") as output:
            output.write("\n# M3 local S3 emulator and ingestion settings\n")
            for key, value in additions.items():
                output.write(f"{key}={value}\n")
        os.chmod(LOCAL, 0o600)
    print("Local M3 environment ready (secret values hidden).")


def extend_m5():
    """Append local M5 transport settings without changing existing secrets."""
    if not LOCAL.is_file():
        raise ValueError(".env is missing; run `make init`")
    values = parse_env(LOCAL)
    template = parse_env(EXAMPLE)
    additions = {key: template[key] for key in
                 ("MATCHING_WEBHOOK_URL", "ALLOW_SYNTHETIC_DEMO") if key not in values}
    if "MATCHING_WEBHOOK_SECRET" not in values:
        additions["MATCHING_WEBHOOK_SECRET"] = secrets.token_hex(32)
    validate(values | additions)
    if additions:
        with LOCAL.open("a", encoding="utf-8") as output:
            output.write("\n# M5 local matching transport and synthetic-demo isolation\n")
            for key, value in additions.items():
                output.write(f"{key}={value}\n")
        os.chmod(LOCAL, 0o600)
    print("Local M5 environment ready (secret values hidden).")


def extend_m6():
    """Append safe, mock-only notification defaults to the ignored local environment."""
    if not LOCAL.is_file():
        raise ValueError(".env is missing; run `make init`")
    values = parse_env(LOCAL)
    template = parse_env(EXAMPLE)
    keys = ("NOTIFICATION_MODE", "NOTIFICATION_TRANSPORT", "NOTIFICATION_SES_ENABLED",
            "NOTIFICATION_TEST_EMAIL", "NOTIFICATION_FROM_EMAIL", "NOTIFICATION_WEBHOOK_URL")
    additions = {key: template[key] for key in keys if key not in values}
    validate(values | additions)
    if additions:
        with LOCAL.open("a", encoding="utf-8") as output:
            output.write("\n# M6 safe local notification settings\n")
            for key, value in additions.items():
                output.write(f"{key}={value}\n")
        os.chmod(LOCAL, 0o600)
    print("Local M6 notification environment ready (no real recipient sends enabled).")


def extend_m7():
    """Append the local-only browser origin to an existing environment."""
    if not LOCAL.is_file():
        raise ValueError(".env is missing; run `make init`")
    values = parse_env(LOCAL)
    template = parse_env(EXAMPLE)
    additions = {"FRONTEND_ORIGIN": template["FRONTEND_ORIGIN"]} if "FRONTEND_ORIGIN" not in values else {}
    validate(values | additions)
    if additions:
        with LOCAL.open("a", encoding="utf-8") as output:
            output.write("\n# M7 browser origin (local only)\n")
            for key, value in additions.items():
                output.write(f"{key}={value}\n")
        os.chmod(LOCAL, 0o600)
    print("Local M7 browser origin ready.")


def extend_m9_1():
    """Append a distinct local n8n-to-helper signing key, preserving older secrets."""
    if not LOCAL.is_file():
        raise ValueError(".env is missing; run `make init`")
    values = parse_env(LOCAL)
    additions = {}
    if "INTERNAL_STEP_KEY_ID" not in values:
        additions["INTERNAL_STEP_KEY_ID"] = "local-v1"
    if "INTERNAL_STEP_SECRET" not in values:
        additions["INTERNAL_STEP_SECRET"] = secrets.token_hex(32)
    if "INTERNAL_STEP_PREVIOUS_KEY_ID" not in values:
        additions["INTERNAL_STEP_PREVIOUS_KEY_ID"] = ""
    if "INTERNAL_STEP_PREVIOUS_SECRET" not in values:
        additions["INTERNAL_STEP_PREVIOUS_SECRET"] = ""
    validate(values | additions)
    if additions:
        with LOCAL.open("a", encoding="utf-8") as output:
            output.write("\n# M9.1 private n8n-to-helper signing and optional key rotation\n")
            for key, value in additions.items():
                output.write(f"{key}={value}\n")
        os.chmod(LOCAL, 0o600)
    print("Local internal step signing ready (secret hidden).")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ("init", "check", "extend", "extend-m3", "extend-m5", "extend-m6", "extend-m7", "extend-m9-1"):
            raise ValueError("usage: python3 scripts/local_env.py {init|check|extend|extend-m3|extend-m5|extend-m6|extend-m7|extend-m9-1}")
        {"init": init, "check": check, "extend": extend, "extend-m3": extend_m3,
         "extend-m5": extend_m5, "extend-m6": extend_m6, "extend-m7": extend_m7,
         "extend-m9-1": extend_m9_1}[sys.argv[1]]()
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
