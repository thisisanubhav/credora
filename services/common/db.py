"""Small synchronous database boundary for Lambda and local tooling."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


def database_url(*, role: str = "runtime", database: str | None = None) -> URL:
    """Construct a URL without string interpolation or logging credentials."""
    if role not in {"runtime", "migration"}:
        raise ValueError("role must be runtime or migration")
    prefix = "APP_DB" if role == "runtime" else "POSTGRES"
    username = os.environ.get(f"{prefix}_USER")
    password = os.environ.get(f"{prefix}_PASSWORD")
    name = database or os.environ.get("POSTGRES_DB")
    if not username or not password or not name:
        raise ValueError(f"missing {prefix} credentials or POSTGRES_DB")
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    if not 1 <= port <= 65535:
        raise ValueError("invalid POSTGRES_PORT")
    return URL.create(
        "postgresql+psycopg",
        username=username,
        password=password,
        host=host,
        port=port,
        database=name,
    )


def make_engine(*, role: str = "runtime", database: str | None = None) -> Engine:
    # NullPool avoids retaining idle Lambda connections against a small RDS instance.
    return create_engine(database_url(role=role, database=database), poolclass=NullPool)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """One transaction; commit on success, rollback and close on failure."""
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        with session.begin():
            yield session
