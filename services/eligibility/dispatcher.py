"""At-least-once signed outbox delivery; no user rows leave PostgreSQL."""

from __future__ import annotations

import os
import random
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.engine import Engine

from services.common.db import make_engine, session_scope
from services.common.models import OutboxEvent, WorkflowExecution
from services.eligibility.transport import signature

LEASE_SECONDS = 90
MAX_ATTEMPTS = 12


def reconcile_stale(engine: Engine) -> int:
    """Requeue an acknowledged event only when matching has stopped making progress."""
    now = datetime.now(UTC)
    changed = 0
    with session_scope(engine) as session:
        rows = session.execute(select(OutboxEvent, WorkflowExecution).outerjoin(
            WorkflowExecution, WorkflowExecution.event_id == OutboxEvent.event_id,
        ).where(OutboxEvent.event_type == "upload_batch.ready.v1",
                OutboxEvent.status == "delivered",
                or_(WorkflowExecution.id.is_(None), WorkflowExecution.status != "succeeded")).with_for_update(
            of=OutboxEvent, skip_locked=True).limit(100)).all()
        for event, run in rows:
            if run is not None and run.status == "succeeded":
                continue
            heartbeat = run.metrics.get("heartbeat_at") if run is not None else None
            stalled = (run is None or run.status in {"failed", "partial"}
                       or (run.status == "running" and
                           (not heartbeat or datetime.fromisoformat(heartbeat) < now - timedelta(minutes=15))))
            if stalled:
                event.status = "pending"
                event.next_attempt_at = now
                event.last_error_code = "matching_stalled"
                changed += 1
    return changed


def claim_due(engine: Engine, *, only_event_id: uuid.UUID | None = None) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    with session_scope(engine) as session:
        query = select(OutboxEvent).where(
            OutboxEvent.event_type == "upload_batch.ready.v1",
            or_((OutboxEvent.status == "pending") & (OutboxEvent.next_attempt_at <= now),
                (OutboxEvent.status == "processing") & (OutboxEvent.claim_expires_at < now)),
        )
        if only_event_id is not None:
            query = query.where(OutboxEvent.event_id == only_event_id)
        event = session.scalar(query.order_by(
            OutboxEvent.next_attempt_at, OutboxEvent.event_id).with_for_update(skip_locked=True).limit(1))
        if event is None:
            return None
        event.status = "processing"
        event.claimed_at = now
        event.claim_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        event.retry_count += 1
        return {"event_id": str(event.event_id), "event_type": event.event_type,
                "batch_id": str(event.aggregate_id), "attempt": event.retry_count,
                "claim_expires_at": event.claim_expires_at}


def finish_attempt(engine: Engine, event_id: uuid.UUID, claim_expires_at: datetime,
                   *, delivered: bool, permanent: bool = False, error_code: str | None = None) -> bool:
    now = datetime.now(UTC)
    with session_scope(engine) as session:
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.event_id == event_id).with_for_update())
        if event is None or event.status != "processing" or event.claim_expires_at != claim_expires_at:
            return False  # A newer claim owns the event; never acknowledge it for another worker.
        event.claimed_at = None
        event.claim_expires_at = None
        event.last_error_code = error_code
        if delivered:
            event.status = "delivered"
            event.processed_at = now
        elif permanent or event.retry_count >= MAX_ATTEMPTS:
            event.status = "failed_permanent"
        else:
            event.status = "pending"
            event.next_attempt_at = now + timedelta(seconds=min(3600, 5 * (2 ** min(event.retry_count, 9)))
                                                     + random.uniform(0, 2))
        return True


def dispatch_once(engine: Engine, *, client: httpx.Client | None = None,
                  only_event_id: uuid.UUID | None = None) -> str:
    if only_event_id is None:
        reconcile_stale(engine)
    claim = claim_due(engine, only_event_id=only_event_id)
    if claim is None:
        return "idle"
    body = {key: claim[key] for key in ("event_id", "event_type", "batch_id")}
    secret = os.environ.get("MATCHING_WEBHOOK_SECRET", "")
    url = os.environ.get("MATCHING_WEBHOOK_URL", "")
    if len(secret) < 32 or not url.startswith(("http://127.0.0.1:", "http://n8n:5678/")):
        finish_attempt(engine, uuid.UUID(claim["event_id"]), claim["claim_expires_at"],
                       delivered=False, permanent=True, error_code="transport_unconfigured")
        return "failed_permanent"
    timestamp = str(int(time.time()))
    headers = {"X-Loan-Event-Id": claim["event_id"], "X-Loan-Timestamp": timestamp,
               "X-Loan-Signature": signature(body, timestamp, secret)}
    owned = client is None
    if client is None:
        client = httpx.Client(timeout=httpx.Timeout(25.0, connect=3.0), trust_env=False)
    try:
        try:
            response = client.post(url, json=body, headers=headers)
            acknowledgement = response.json() if response.status_code == 202 else {}
            delivered = (response.status_code == 202
                         and acknowledgement.get("run_id") is not None
                         and acknowledgement.get("batch_id") == body["batch_id"])
            permanent = response.status_code in {400, 401, 403, 422}
            code = None if delivered else f"webhook_http_{response.status_code}"
        except (httpx.TransportError, ValueError):
            delivered, permanent, code = False, False, "webhook_transport_or_response"
        finish_attempt(engine, uuid.UUID(claim["event_id"]), claim["claim_expires_at"],
                       delivered=delivered, permanent=permanent, error_code=code)
        return "delivered" if delivered else ("failed_permanent" if permanent else "retry_scheduled")
    finally:
        if owned:
            client.close()


def main() -> None:
    if sys.argv[1:] not in (["--once"], ["--watch"]):
        raise SystemExit("usage: python -m services.eligibility.dispatcher {--once|--watch}")
    engine = make_engine()
    try:
        while True:
            print(f"dispatcher: {dispatch_once(engine)}")
            if sys.argv[1] == "--once":
                break
            time.sleep(5)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
