"""Isolated, no-send tests for event-specific notification recovery preparation."""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.pool import StaticPool

from services.common.db import session_scope
from services.common.models import (
    NotificationLog,
    OutboxEvent,
    UploadBatch,
    User,
    WorkflowExecution,
)
from services.notifications.content import idempotency_key
from services.notifications.recovery import (
    ACCEPT_NODE,
    PREFLIGHT_NODE,
    SES_NODE,
    prepare_recovery,
)
from services.notifications.storage import accept_event, next_reservation
from tests.notifications.test_notifications import _isolate_single_demo_match, setup_data  # noqa: F401

TOKEN = "local-test-recovery-authorization-000000000001"
N8N_ID = 176


def _evidence(run_id: uuid.UUID, batch_id: uuid.UUID, *, status: str = "error",
              ses_seen: bool = False, bound_run: uuid.UUID | None = None):
    values: list[object] = [{}]

    def add(value: object) -> str:
        values.append(value)
        return str(len(values) - 1)

    payload = add({"run_id": add(str(bound_run or run_id)),
                   "batch_id": add(str(batch_id))})
    accept = add({"data": add({"main": add([add([add({"json": payload})])])})})
    preflight = add({"error": add({"message": "notification_step_rejected"})})
    run_data = {ACCEPT_NODE: add([accept]), PREFLIGHT_NODE: add([preflight])}
    if ses_seen:
        run_data[SES_NODE] = add([add({"data": add({})})])
    values[0] = {"resultData": add({"runData": add(run_data)})}
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE execution_entity '
                                '(id integer PRIMARY KEY, "workflowId" text, status text, '
                                '"stoppedAt" text)'))
        connection.execute(text('CREATE TABLE execution_data '
                                '("executionId" integer PRIMARY KEY, data text)'))
        connection.execute(text('INSERT INTO execution_entity '
                                '(id, "workflowId", status, "stoppedAt") '
                                'VALUES (:id, :workflow, :status, :stopped)'),
                           {"id": N8N_ID, "workflow": "loanNotificationsM6",
                            "status": status, "stopped": "2026-10-16T10:35:21Z"})
        connection.execute(text('INSERT INTO execution_data ("executionId", data) '
                                'VALUES (:id, :data)'),
                           {"id": N8N_ID, "data": json.dumps(values)})
    return engine


@pytest.fixture
def recoverable(setup_data, monkeypatch):
    app, batch_id, event_id, _ = setup_data
    user_id = _isolate_single_demo_match(setup_data)
    monkeypatch.setenv("NOTIFICATION_TRANSPORT", "ses")
    monkeypatch.setenv("NOTIFICATION_SES_ENABLED", "1")
    monkeypatch.setenv("NOTIFICATION_TEST_EMAIL", "controlled@example.test")
    run_id = uuid.UUID(accept_event(app, event_id=event_id, batch_id=batch_id)["run_id"])
    notification_id = uuid.UUID(next_reservation(app, run_id)["notification_id"])
    monkeypatch.setenv("NOTIFICATION_TRANSPORT", "mock")
    monkeypatch.setenv("NOTIFICATION_SES_ENABLED", "0")
    monkeypatch.setenv("NOTIFICATION_SES_MAX_ATTEMPTS", "0")
    monkeypatch.setenv("NOTIFICATION_RECOVERY_TOKEN", TOKEN)
    with session_scope(app) as session:
        event = session.get(OutboxEvent, event_id)
        event.status = "delivered"
        event.retry_count = 1
        run = session.get(WorkflowExecution, run_id)
        run.metrics = {**run.metrics,
                       "heartbeat_at": (datetime.now(UTC) - timedelta(minutes=20)).isoformat()}
        assert session.get(NotificationLog, notification_id).recipient_alias == "controlled@example.test"
    n8n = _evidence(run_id, batch_id)
    yield {"app": app, "n8n": n8n, "batch": batch_id, "event": event_id,
           "run": run_id, "notification": notification_id,
           "key": idempotency_key(batch_id, user_id)}
    n8n.dispose()


def _prepare(case, **overrides):
    args = {"event_id": case["event"], "batch_id": case["batch"],
            "notification_key": case["key"], "n8n_execution_id": N8N_ID,
            "authorization": TOKEN}
    args.update(overrides)
    return prepare_recovery(case["app"], case["n8n"], **args)


def test_valid_recovery_is_audited_held_and_does_not_send(recoverable):
    case = recoverable
    with session_scope(case["app"]) as session:
        other = OutboxEvent(event_id=uuid.uuid4(), event_type="upload_batch.ready.v1",
                            aggregate_id=case["batch"], payload={"test": True})
        session.add(other)
        other_id = other.event_id
    audit_id = _prepare(case)
    with session_scope(case["app"]) as session:
        event = session.get(OutboxEvent, case["event"])
        log = session.get(NotificationLog, case["notification"])
        audit = session.get(WorkflowExecution, audit_id)
        assert event.status == "pending" and event.next_attempt_at.year == 9999
        assert event.retry_count == 1 and event.last_error_code == "manual_recovery_held"
        assert (log.status, log.attempt_count, log.ses_message_id) == ("reserved", 0, None)
        assert audit.workflow_type == "outbox_reconcile" and audit.parent_execution_id == case["run"]
        assert audit.metrics["notification_id"] == str(log.id)
        assert session.get(OutboxEvent, other_id).status == "pending"
        assert session.scalar(select(func.count()).select_from(NotificationLog)) == 1
    with pytest.raises(ValueError, match="recovery_event_not_eligible"):
        _prepare(case)


@pytest.mark.parametrize("override,expected", [
    ({"event_id": uuid.UUID("00000000-0000-4000-8000-000000000001")}, "event_not_eligible"),
    ({"batch_id": uuid.UUID("00000000-0000-4000-8000-000000000002")}, "event_not_eligible"),
    ({"notification_key": "0" * 64}, "reservation_not_eligible"),
    ({"authorization": "bad"}, "not_authorized"),
])
def test_wrong_scope_or_authorization_rejected(recoverable, override, expected):
    with pytest.raises(ValueError, match=expected):
        _prepare(recoverable, **override)


@pytest.mark.parametrize("state,attempts,provider", [
    ("sending", 1, None), ("reserved", 1, None),
    ("reserved", 0, "provider-id"), ("ambiguous", 1, None),
])
def test_provider_started_or_ambiguous_is_rejected(recoverable, state, attempts, provider):
    with session_scope(recoverable["app"]) as session:
        log = session.get(NotificationLog, recoverable["notification"])
        log.status, log.attempt_count, log.ses_message_id = state, attempts, provider
    with pytest.raises(ValueError, match="reservation_not_eligible"):
        _prepare(recoverable)


def test_recent_run_is_not_recovered(recoverable):
    with session_scope(recoverable["app"]) as session:
        run = session.get(WorkflowExecution, recoverable["run"])
        run.metrics = {**run.metrics, "heartbeat_at": datetime.now(UTC).isoformat()}
    with pytest.raises(ValueError, match="run_not_stale"):
        _prepare(recoverable)


def test_ses_node_or_mismatched_n8n_evidence_is_rejected(recoverable):
    for evidence in (_evidence(recoverable["run"], recoverable["batch"], ses_seen=True),
                     _evidence(recoverable["run"], recoverable["batch"], status="running"),
                     _evidence(recoverable["run"], recoverable["batch"], bound_run=uuid.uuid4())):
        try:
            with pytest.raises(ValueError):
                prepare_recovery(recoverable["app"], evidence, event_id=recoverable["event"],
                                 batch_id=recoverable["batch"],
                                 notification_key=recoverable["key"],
                                 n8n_execution_id=N8N_ID, authorization=TOKEN)
        finally:
            evidence.dispose()


def test_csv_recipient_cannot_be_recovered(recoverable):
    with session_scope(recoverable["app"]) as session:
        log = session.get(NotificationLog, recoverable["notification"])
        user = session.get(User, log.user_id)
        log.recipient_alias = user.email
    with pytest.raises(ValueError, match="recipient_not_controlled"):
        _prepare(recoverable)


def test_concurrent_recovery_has_one_winner(recoverable):
    def attempt(_: int) -> str:
        try:
            _prepare(recoverable)
            return "prepared"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["prepared", "rejected"]
    with session_scope(recoverable["app"]) as session:
        assert session.scalar(select(func.count()).select_from(WorkflowExecution).where(
            WorkflowExecution.workflow_type == "outbox_reconcile")) == 1


def test_recovery_token_is_required(recoverable, monkeypatch):
    monkeypatch.delenv("NOTIFICATION_RECOVERY_TOKEN")
    with pytest.raises(ValueError, match="not_authorized"):
        _prepare(recoverable)
