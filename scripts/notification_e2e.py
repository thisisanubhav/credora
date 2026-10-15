"""Real local CSV→S3→Workflow B→Workflow C path; mock acceptance sends no email."""

from __future__ import annotations

import os
import time
import uuid

import httpx
import psycopg
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.main import app
from scripts.local_s3 import ensure_bucket
from scripts.seed_notification_demo import seed_notification_demo
from services.common.db import make_engine, session_scope
from services.common.models import (
    Match,
    NotificationLog,
    NotificationMatch,
    OutboxEvent,
    UploadBatch,
    User,
    WorkflowExecution,
)
from services.eligibility.dispatcher import dispatch_once
from services.eligibility.transport import signature
from services.ingestion.config import Settings, s3_client
from services.ingestion.worker import lambda_handler


def _wait_for_run(engine, batch_id: uuid.UUID, kind: str) -> WorkflowExecution:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        with session_scope(engine) as session:
            run = session.scalar(select(WorkflowExecution).where(
                WorkflowExecution.upload_batch_id == batch_id,
                WorkflowExecution.workflow_type == kind))
            if run is not None and run.status == "succeeded":
                return run
        time.sleep(1)
    raise RuntimeError(f"{kind} workflow did not finish for batch {batch_id}")


def _dispatch_when_due(engine, event_id: uuid.UUID) -> None:  # type: ignore[no-untyped-def]
    # PostgreSQL's transaction clock may put next_attempt_at just after the
    # host clock; a one-shot assertion must tolerate a briefly not-yet-due row.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        outcome = dispatch_once(engine, only_event_id=event_id)
        if outcome == "delivered":
            return
        if outcome != "idle":
            raise RuntimeError(f"outbox dispatch returned {outcome}")
        time.sleep(0.1)
    raise RuntimeError("outbox event did not become due")


def _assert_n8n_terminal(run_id: uuid.UUID, workflow_id: str, final_node: str) -> int:
    """Cross-check n8n's own terminal record, not only the helper's run state."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with psycopg.connect(host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
                             port=int(os.getenv("POSTGRES_PORT", "5432")),
                             dbname=os.environ["N8N_DB_NAME"], user=os.environ["N8N_DB_USER"],
                             password=os.environ["N8N_DB_PASSWORD"]) as connection:
            row = connection.execute(
                'SELECT e.id, e.status, e."stoppedAt", '
                "position(%s in d.data::text) > 0 "
                'FROM execution_entity e JOIN execution_data d ON d."executionId" = e.id '
                'WHERE e."workflowId" = %s AND position(%s in d.data::text) > 0 '
                'ORDER BY e.id DESC LIMIT 1',
                (final_node, workflow_id, str(run_id)),
            ).fetchone()
        if row is not None:
            execution_id, status, stopped_at, reached_final = row
            if status == "success" and stopped_at is not None and reached_final:
                return int(execution_id)
            if status == "error":
                raise RuntimeError(f"n8n {workflow_id} execution {execution_id} errored")
        time.sleep(0.2)
    raise RuntimeError(f"n8n {workflow_id} did not reach terminal success")


def main() -> None:
    if os.environ.get("ALLOW_SYNTHETIC_DEMO") != "1" or os.environ.get("NOTIFICATION_TRANSPORT") != "mock":
        raise RuntimeError("local E2E requires explicitly enabled synthetic data and mock-only delivery")
    engine = make_engine()
    try:
        seed_notification_demo(engine)
        ensure_bucket()
        content = (b"user_id,email,monthly_income,credit_score,employment_status,age\n"
                   b"one,one@example.com,50000,710,Salaried,30\n"
                   b"two,two@example.com,50000,760,Salaried,30\n"
                   b"none,none@example.com,50000,699,Salaried,30\n")
        with TestClient(app) as api:
            response = api.post("/uploads", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
                "filename": "notification-demo.csv", "size_bytes": len(content),
                "content_type": "text/csv", "demo_mode": True})
            assert response.status_code == 201, response.status_code
            upload = response.json()["upload"]
            batch_id = uuid.UUID(response.json()["batch_id"])
            sent = httpx.post(upload["url"], data=upload["fields"],
                              files={"file": ("notification-demo.csv", content, "text/csv")}, timeout=30)
            assert sent.status_code in (200, 201, 204), sent.status_code
            settings = Settings.from_env()
            key = upload["fields"]["key"]
            etag = s3_client(settings).head_object(Bucket=settings.bucket, Key=key)["ETag"].strip('"')
            event = {"Records": [{"eventName": "ObjectCreated:Post", "s3": {
                "bucket": {"name": settings.bucket}, "object": {"key": key, "eTag": etag}}}]}
            assert lambda_handler(event, None)["results"] == ["processed"]
        with session_scope(engine) as session:
            batch = session.get(UploadBatch, batch_id)
            assert batch is not None and batch.accepted_rows == 3
            ready = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == batch_id,
                                                              OutboxEvent.event_type == "upload_batch.ready.v1"))
            assert ready is not None
            ready_id = ready.event_id
        _dispatch_when_due(engine, ready_id)
        matching = _wait_for_run(engine, batch_id, "matching")
        with session_scope(engine) as session:
            matches = session.execute(select(User.source_user_id, func.count(Match.id)).outerjoin(
                Match, Match.user_id == User.id).where(User.upload_batch_id == batch_id).group_by(
                User.source_user_id)).all()
            assert {name: count for name, count in matches} == {"one": 1, "two": 2, "none": 0}, matches
            completed = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == batch_id,
                                                                  OutboxEvent.event_type == "matching.completed.v1"))
            assert completed is not None
            completed_id = completed.event_id
        _dispatch_when_due(engine, completed_id)
        notification = _wait_for_run(engine, batch_id, "notification")
        matching_execution = _assert_n8n_terminal(matching.id, "loanMatchingM5", "Execution Summary")
        notification_execution = _assert_n8n_terminal(notification.id, "loanNotificationsM6",
                                                       "Notification Execution Summary")
        with session_scope(engine) as session:
            logs = session.scalars(select(NotificationLog).where(
                NotificationLog.workflow_execution_id == notification.id)).all()
            assert len(logs) == 2 and all(log.status == "mocked" and log.ses_message_id is None for log in logs)
            groups = sorted(session.scalar(select(func.count()).select_from(NotificationMatch).where(
                NotificationMatch.notification_id == log.id)) or 0 for log in logs)
            assert groups == [1, 2]
            assert all(log.recipient_alias == os.environ["NOTIFICATION_TEST_EMAIL"].lower() for log in logs)
            assert all(log.recipient_alias not in {"one@example.com", "two@example.com",
                                                   "none@example.com"} for log in logs)
            before = session.scalar(select(func.count()).select_from(NotificationLog).join(
                User, NotificationLog.user_id == User.id).where(User.upload_batch_id == batch_id))
        body = {"event_id": str(completed_id), "event_type": "matching.completed.v1", "batch_id": str(batch_id)}
        timestamp = str(int(time.time()))
        replay = httpx.post(os.environ["NOTIFICATION_WEBHOOK_URL"], json=body, headers={
            "X-Loan-Event-Id": str(completed_id), "X-Loan-Timestamp": timestamp,
            "X-Loan-Signature": signature(body, timestamp, os.environ["MATCHING_WEBHOOK_SECRET"]),
        }, timeout=30)
        assert replay.status_code == 202 and replay.json()["state"] == "succeeded", replay.status_code
        with session_scope(engine) as session:
            after = session.scalar(select(func.count()).select_from(NotificationLog).join(
                User, NotificationLog.user_id == User.id).where(User.upload_batch_id == batch_id))
            assert before == after == 2
        print(f"PASS: batch={batch_id} matching_run={matching.id} notification_run={notification.id}; "
              "3 matches grouped into 2 mock-only notifications (1+2); 1 user had none; signed replay added zero.")
        print(f"PASS: terminal n8n executions B={matching_execution} C={notification_execution} reached summaries.")
        print("PASS: no SES call or actual email delivery occurred; CSV addresses were never recipients.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
