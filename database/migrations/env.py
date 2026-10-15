"""Alembic environment; only the migration/bootstrap role may run DDL."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from services.common.db import database_url, make_engine
from services.common.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(role="migration", database=os.environ.get("DATABASE_NAME")).render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(connection=supplied_connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = make_engine(role="migration", database=os.environ.get("DATABASE_NAME"))
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
