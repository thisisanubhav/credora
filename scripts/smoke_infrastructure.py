"""Read-only checks for the M1 Compose stack (Python standard library only)."""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from local_env import LOCAL, parse_env, validate

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker", "compose", "--project-directory", ".", "--env-file", ".env",
    "-f", "infrastructure/docker-compose.yml",
]


def run(args, check=True):
    result = subprocess.run(args, check=False, cwd=ROOT, text=True, capture_output=True)
    if check and result.returncode:
        # Compose config and container details may contain credentials. Do not echo them.
        raise RuntimeError(f"command failed (exit {result.returncode}): {args[0]}")
    return result


def compose(*args, check=True):
    return run(COMPOSE + list(args), check=check)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def inspect(container_id, format_string):
    return json.loads(run(["docker", "inspect", "--format", format_string, container_id]).stdout)


def check_static(config):
    services = config.get("services", {})
    require(set(services) == {"postgres", "n8n", "localstack", "discovery"}, "expected postgres, n8n, localstack, discovery")
    require(set(config.get("volumes", {})) == {"postgres_data", "n8n_data", "localstack_data"}, "named volumes missing")
    for name in ("postgres", "n8n", "localstack", "discovery"):
        service = services[name]
        require(service.get("healthcheck"), f"{name} has no healthcheck")
        require(service.get("restart") == "unless-stopped", f"{name} has no restart policy")
        require(service.get("networks"), f"{name} has no Compose network")
        ports = service.get("ports", [])
        if name == "discovery":
            require(not ports, "discovery must not publish a host port")
        else:
            require(len(ports) == 1 and ports[0].get("host_ip") == "127.0.0.1", f"{name} is not loopback-only")
            expected_volume = {"postgres": "postgres_data", "n8n": "n8n_data", "localstack": "localstack_data"}[name]
            require(any(volume.get("type") == "volume" and volume.get("source") == expected_volume
                        for volume in service.get("volumes", [])), f"{name} has no persistent named volume")
    require(services["n8n"].get("depends_on", {}).get("postgres", {}).get("condition") == "service_healthy",
            "n8n does not wait for healthy PostgreSQL")
    n8n_env = services["n8n"].get("environment", {})
    require(n8n_env.get("DB_TYPE") == "postgresdb" and n8n_env.get("DB_POSTGRESDB_HOST") == "postgres",
            "n8n is not configured for PostgreSQL over the Compose network")
    print("PASS: Compose structure, health checks, startup order, named volumes, and loopback bindings")


def check_runtime(values):
    ids = {}
    for name in ("postgres", "n8n", "localstack", "discovery"):
        ids[name] = compose("ps", "-q", name).stdout.strip()
        require(ids[name], f"{name} container is not running")
        state = inspect(ids[name], "{{json .State}}")
        require(state.get("Running") and state.get("Health", {}).get("Status") == "healthy",
                f"{name} container is not healthy")
        mounts = inspect(ids[name], "{{json .Mounts}}")
        if name != "discovery":
            expected = {"postgres": "postgres_data", "n8n": "n8n_data", "localstack": "localstack_data"}[name]
            require(any(mount.get("Type") == "volume" and mount.get("Name", "").endswith("_" + expected)
                        for mount in mounts), f"{name} named volume is not mounted")
        ports = inspect(ids[name], "{{json .NetworkSettings.Ports}}")
        if name == "discovery":
            require(not any(ports.values()), "discovery runtime port is published")
        else:
            expected_port = {"postgres": "5432/tcp", "n8n": "5678/tcp", "localstack": "4566/tcp"}[name]
            bindings = ports.get(expected_port) or []
            require(len(bindings) == 1 and bindings[0].get("HostIp") == "127.0.0.1",
                    f"{name} runtime port is not bound only to loopback")
    print("PASS: PostgreSQL and n8n are healthy with named volumes and loopback-only runtime ports")

    postgres_networks = inspect(ids["postgres"], "{{json .NetworkSettings.Networks}}")
    n8n_networks = inspect(ids["n8n"], "{{json .NetworkSettings.Networks}}")
    require(set(postgres_networks) & set(n8n_networks), "services do not share a Compose network")
    tcp_probe = (
        "const net=require('node:net');"
        "const s=net.createConnection({host:'postgres',port:5432});"
        "s.setTimeout(3000);"
        "s.on('connect',()=>{s.end();process.exit(0)});"
        "s.on('error',()=>process.exit(1));s.on('timeout',()=>process.exit(1));"
    )
    compose("exec", "-T", "n8n", "node", "-e", tcp_probe)
    print("PASS: n8n resolves and reaches PostgreSQL on the Compose network")

    app_sql = "SELECT current_database() || '|' || current_user || '|' || pg_encoding_to_char(encoding) FROM pg_database WHERE datname=current_database()"
    app_command = 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -qAt -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"'
    app = compose("exec", "-T", "postgres", "sh", "-c", app_command, "sh", app_sql).stdout.strip()
    require(app == f"{values['POSTGRES_DB']}|{values['POSTGRES_USER']}|UTF8", "application database auth/name/encoding failed")
    n8n_sql = "SELECT current_database() || '|' || current_user || '|' || pg_encoding_to_char(encoding) FROM pg_database WHERE datname=current_database()"
    n8n_command = 'PGPASSWORD="$N8N_DB_PASSWORD" psql -X -qAt -h 127.0.0.1 -U "$N8N_DB_USER" -d "$N8N_DB_NAME" -c "$1"'
    n8n = compose("exec", "-T", "postgres", "sh", "-c", n8n_command, "sh", n8n_sql).stdout.strip()
    require(n8n == f"{values['N8N_DB_NAME']}|{values['N8N_DB_USER']}|UTF8", "n8n database auth/name/encoding failed")
    print("PASS: authenticated UTF-8 connections to separate application and n8n databases")

    cross_db_command = 'PGPASSWORD="$N8N_DB_PASSWORD" psql -X -qAt -h 127.0.0.1 -U "$N8N_DB_USER" -d "$POSTGRES_DB" -c "SELECT 1"'
    cross_db = compose("exec", "-T", "postgres", "sh", "-c", cross_db_command, check=False)
    require(cross_db.returncode != 0, "n8n internal role can connect to the application database")
    print("PASS: n8n internal role cannot connect to the application database")

    query = "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    app_tables = set(compose("exec", "-T", "postgres", "sh", "-c", app_command, "sh", query).stdout.splitlines())
    n8n_tables = set(compose("exec", "-T", "postgres", "sh", "-c", n8n_command, "sh", query).stdout.splitlines())
    m2_tables = {"alembic_version", "upload_batches", "users", "product_sources", "loan_products",
                 "matches", "workflow_executions", "outbox_events", "notification_logs", "notification_matches", "upload_row_errors",
                 "internal_request_nonces"}
    require(not app_tables or app_tables == m2_tables, "unexpected application database tables")
    require(n8n_tables and not (n8n_tables & m2_tables), "n8n persistence is not isolated")
    print("PASS: application schema is isolated from n8n internal tables")

    url = f"http://127.0.0.1:{values['N8N_PORT']}/healthz"
    for attempt in range(10):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                require(response.status == 200, "n8n health endpoint did not return HTTP 200")
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 9:
                raise RuntimeError("n8n HTTP health endpoint is unreachable")
            time.sleep(1)
    print("PASS: n8n HTTP /healthz responds on localhost")


def main():
    values = parse_env(LOCAL)
    validate(values)
    print("PASS: local environment validation")
    config = json.loads(compose("config", "--format", "json").stdout)
    check_static(config)
    if run(["docker", "info", "--format", "{{.ServerVersion}}"], check=False).returncode:
        print("BLOCKED: Docker daemon unavailable; runtime checks were not run")
        return 2
    check_runtime(values)
    print("PASS: all M1 infrastructure smoke checks")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
