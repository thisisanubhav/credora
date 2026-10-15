"""Idempotent local role/test-database setup; never drops a database."""

from __future__ import annotations

import os
import secrets
import sys

import psycopg
from psycopg import sql
from sqlalchemy import text

from services.common.db import make_engine


def admin_connection(database: str, *, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=database,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=autocommit,
    )


def runtime_role() -> None:
    role = os.environ["APP_DB_USER"]
    password = os.environ["APP_DB_PASSWORD"]
    if role in {os.environ["POSTGRES_USER"], os.environ["N8N_DB_USER"]}:
        raise ValueError("runtime role must differ from bootstrap and n8n roles")
    with admin_connection("postgres") as conn, conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cursor.fetchone() is None:
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        else:
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        cursor.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(os.environ["POSTGRES_DB"]), sql.Identifier(role)
            )
        )
    with admin_connection(os.environ["POSTGRES_DB"]) as conn, conn.cursor() as cursor:
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        cursor.execute(
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(
            sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE ON TABLES FROM {}").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE ON upload_batches, product_sources, matches, "
                "workflow_executions, outbox_events, notification_logs, upload_row_errors TO {}"
            ).format(sql.Identifier(role))
        )
        cursor.execute(
            sql.SQL("GRANT SELECT, INSERT ON users, loan_products, notification_matches TO {}").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(
            sql.SQL(
                "GRANT UPDATE (is_current, last_seen_at, retired_at, verification_status) "
                "ON loan_products TO {}"
            ).format(sql.Identifier(role))
        )
    print("Runtime role configured without DDL or DELETE privileges (credentials hidden).")


def test_database(*, ingestion: bool = False, discovery: bool = False) -> None:
    name = os.environ["TEST_DB_NAME"]
    if ingestion:
        name = name.removesuffix("_test") + "_ingestion_test"
    if discovery:
        name = name.removesuffix("_test") + "_discovery_test"
    if not name.endswith("_test") or name in {os.environ["POSTGRES_DB"], os.environ["N8N_DB_NAME"]}:
        raise ValueError("refusing unsafe test database name")
    with admin_connection("postgres", autocommit=True) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if cursor.fetchone() is None:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                    sql.Identifier(name), sql.Identifier(os.environ["POSTGRES_USER"])
                )
            )
        cursor.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
        )
    print("Dedicated test database available (development database untouched).")


def check_connection() -> None:
    engine = make_engine()
    try:
        with engine.connect() as conn:
            if (
                conn.execute(text("SELECT current_database()")).scalar_one()
                != os.environ["POSTGRES_DB"]
            ):
                raise ValueError("connected to an unexpected database")
            if conn.execute(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")).scalar_one():
                raise ValueError("runtime role unexpectedly has schema DDL privileges")
            if conn.execute(text("SELECT has_table_privilege(current_user, 'users', 'DELETE')")).scalar_one():
                raise ValueError("runtime role unexpectedly has DELETE privileges")
            if conn.execute(text("SELECT has_column_privilege(current_user, 'loan_products', 'eligibility_rules', 'UPDATE')")).scalar_one():
                raise ValueError("runtime role can mutate historical eligibility rules")
            if conn.execute(text("SELECT has_table_privilege(current_user, 'alembic_version', 'INSERT')")).scalar_one():
                raise ValueError("runtime role can mutate migration version state")
            if conn.execute(text("SELECT has_table_privilege(current_user, 'users', 'UPDATE')")).scalar_one():
                raise ValueError("runtime role can mutate imported users")
        print("Runtime role connected to the application database (credentials hidden).")
    finally:
        engine.dispose()


def rotate_local_admin() -> None:
    """Rotate the ignored local bootstrap password after accidental console exposure."""
    from pathlib import Path

    env_path = Path(__file__).resolve().parents[1] / ".env"
    old = os.environ["POSTGRES_PASSWORD"]
    new = secrets.token_hex(32)
    with admin_connection("postgres") as conn, conn.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(os.environ["POSTGRES_USER"]), sql.Literal(new)
            )
        )
    source = env_path.read_text(encoding="utf-8")
    expected = f"POSTGRES_PASSWORD={old}"
    if source.count(expected) != 1:
        raise ValueError("local .env admin password line not found uniquely")
    env_path.write_text(source.replace(expected, f"POSTGRES_PASSWORD={new}"), encoding="utf-8")
    os.chmod(env_path, 0o600)
    print("Rotated ignored local bootstrap password (value hidden).")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "runtime-role",
        "test-database",
        "ingestion-test-database",
        "discovery-test-database",
        "check",
        "rotate-admin",
    }:
        raise SystemExit(
            "usage: python -m scripts.db_admin {runtime-role|test-database|ingestion-test-database|discovery-test-database|check|rotate-admin}"
        )
    {
        "runtime-role": runtime_role,
        "test-database": test_database,
        "ingestion-test-database": lambda: test_database(ingestion=True),
        "discovery-test-database": lambda: test_database(discovery=True),
        "check": check_connection,
        "rotate-admin": rotate_local_admin,
    }[sys.argv[1]]()
