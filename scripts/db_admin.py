#!/usr/bin/env python3
"""Idempotent local role/test-database setup; never drops a database."""

from __future__ import annotations

import os
import sys

import psycopg
from psycopg import sql

from services.common.db import database_url
from services.common.db import make_engine
from sqlalchemy import text


def runtime_role() -> None:
    role = os.environ["APP_DB_USER"]
    password = os.environ["APP_DB_PASSWORD"]
    if role in {os.environ["POSTGRES_USER"], os.environ["N8N_DB_USER"]}:
        raise ValueError("runtime role must differ from bootstrap and n8n roles")
    with psycopg.connect(database_url(role="migration", database="postgres").render_as_string(hide_password=False)) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cursor.fetchone() is None:
                cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
            else:
                cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(os.environ["POSTGRES_DB"]), sql.Identifier(role)))
    with psycopg.connect(database_url(role="migration").render_as_string(hide_password=False)) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO {}").format(sql.Identifier(role)))
    print("Runtime role configured without DDL or DELETE privileges (credentials hidden).")


def test_database() -> None:
    name = os.environ["TEST_DB_NAME"]
    if not name.endswith("_test") or name in {os.environ["POSTGRES_DB"], os.environ["N8N_DB_NAME"]}:
        raise ValueError("refusing unsafe test database name")
    with psycopg.connect(database_url(role="migration", database="postgres").render_as_string(hide_password=False), autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cursor.fetchone() is None:
                cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(sql.Identifier(name), sql.Identifier(os.environ["POSTGRES_USER"])))
            cursor.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
    print("Dedicated test database available (development database untouched).")


def check_connection() -> None:
    engine = make_engine()
    try:
        with engine.connect() as conn:
            if conn.execute(text("SELECT current_database()" )).scalar_one() != os.environ["POSTGRES_DB"]:
                raise ValueError("connected to an unexpected database")
        print("Runtime role connected to the application database (credentials hidden).")
    finally:
        engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"runtime-role", "test-database", "check"}:
        raise SystemExit("usage: python -m scripts.db_admin {runtime-role|test-database|check}")
    {"runtime-role": runtime_role, "test-database": test_database, "check": check_connection}[sys.argv[1]]()
