"""Manually prepare one proven-unsent notification; never dispatch or send."""

from __future__ import annotations

import argparse
import getpass
import os
import uuid

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from services.common.db import make_engine
from services.notifications.recovery import prepare_recovery


def n8n_read_engine():  # type: ignore[no-untyped-def]
    user = os.environ.get("N8N_DB_USER")
    password = os.environ.get("N8N_DB_PASSWORD")
    database = os.environ.get("N8N_DB_NAME")
    if not user or not password or not database:
        raise ValueError("n8n_evidence_database_unconfigured")
    url = URL.create("postgresql+psycopg", username=user, password=password,
                     host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
                     port=int(os.environ.get("POSTGRES_PORT", "5432")),
                     database=database)
    return create_engine(url, poolclass=NullPool)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hold exactly one failed notification event; no send")
    parser.add_argument("--prepare", action="store_true", required=True)
    parser.add_argument("--event-id", type=uuid.UUID, required=True)
    parser.add_argument("--batch-id", type=uuid.UUID, required=True)
    parser.add_argument("--n8n-execution-id", type=int, required=True)
    args = parser.parse_args()
    notification_key = os.environ.get("NOTIFICATION_RECOVERY_IDEMPOTENCY_KEY", "")
    if len(notification_key) != 64:
        raise SystemExit("Recovery notification key is not configured")
    token = getpass.getpass("One-time recovery authorization token: ")
    app_engine = make_engine()
    evidence_engine = n8n_read_engine()
    try:
        audit_id = prepare_recovery(
            app_engine, evidence_engine, event_id=args.event_id,
            batch_id=args.batch_id, notification_key=notification_key,
            n8n_execution_id=args.n8n_execution_id, authorization=token,
        )
        print(f"Recovery prepared and held; audit ID: {audit_id}. No event dispatched.")
    finally:
        evidence_engine.dispose()
        app_engine.dispose()


if __name__ == "__main__":
    main()
