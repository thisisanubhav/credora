"""Isolated, no-send tests for event-specific notification recovery preparation."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.pool import StaticPool

from services.common.db import session_scope
from services.common.models import (
    Match,
    NotificationLog,
    OutboxEvent,
    UploadBatch,
    User,
    WorkflowExecution,
)
from services.eligibility.dispatcher import claim_due, finish_attempt
from services.notifications.content import idempotency_key
from services.notifications.recovery import (
    ACCEPT_NODE,
    PREFLIGHT_NODE,
    SES_NODE,
    prepare_recovery,
    release_recovery,
)
from services.notifications.storage import accept_event, next_reservation

pytest_plugins = ["tests.notifications.test_notifications"]

TOKEN = "local-test-recovery-authorization-000000000001"
RELEASE_TOKEN = "local-test-release-authorization-0000000000001"
N8N_ID = 176


def _isolate_single_demo_match(data):  # type: ignore[no-untyped-def]
    app, batch_id, _, _ = data
    with session_scope(app) as session:
        user_id = session.scalar(select(Match.user_id).group_by(Match.user_id).having(func.count() == 1))
        assert user_id is not None
        session.execute(delete(Match).where(Match.user_id != user_id))
        session.execute(delete(User).where(User.id != user_id))
        batch = session.get(UploadBatch, batch_id)
        assert batch is not None
        batch.accepted_rows = batch.total_rows = 1
    return user_id


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


@pytest.fixture
def held(recoverable, monkeypatch):
    monkeypatch.setenv("NOTIFICATION_RECOVERY_RELEASE_TOKEN", RELEASE_TOKEN)
    return {**recoverable, "audit": _prepare(recoverable)}


def _release(case, **overrides):
    args = {"event_id": case["event"], "batch_id": case["batch"],
            "notification_key": case["key"], "recovery_audit_id": case["audit"],
            "authorization": RELEASE_TOKEN}
    args.update(overrides)
    return release_recovery(case["app"], case["n8n"], **args)


def test_release_is_audited_targeted_only_and_does_not_dispatch(held):
    case = held
    release_id = _release(case)
    with session_scope(case["app"]) as session:
        event = session.get(OutboxEvent, case["event"])
        log = session.get(NotificationLog, case["notification"])
        audit = session.get(WorkflowExecution, release_id)
        assert event.status == "pending" and event.next_attempt_at <= datetime.now(UTC)
        assert event.payload["recovery_dispatch_scope"] == "targeted_only"
        assert event.retry_count == 1 and event.last_error_code == "manual_recovery_released"
        assert (log.status, log.attempt_count, log.ses_message_id) == ("reserved", 0, None)
        assert audit.metrics["preparation_audit_id"] == str(case["audit"])
        assert audit.metrics["notification_id"] == str(log.id)
    assert claim_due(case["app"]) is None
    with session_scope(case["app"]) as session:
        assert session.get(OutboxEvent, case["event"]).status == "pending"
    # An explicit ID can claim it; a retry must remain isolated from queue sweeps.
    claim = claim_due(case["app"], only_event_id=case["event"])
    assert claim is not None and claim["event_id"] == str(case["event"])
    assert finish_attempt(case["app"], case["event"], claim["claim_expires_at"],
                          delivered=False, error_code="test_timeout")
    with session_scope(case["app"]) as session:
        event = session.get(OutboxEvent, case["event"])
        event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    assert claim_due(case["app"]) is None


@pytest.mark.parametrize("override,expected", [
    ({"event_id": uuid.UUID("00000000-0000-4000-8000-000000000011")}, "event_not_held"),
    ({"batch_id": uuid.UUID("00000000-0000-4000-8000-000000000012")}, "event_not_held"),
    ({"notification_key": "0" * 64}, "reservation_not_eligible"),
    ({"recovery_audit_id": uuid.UUID("00000000-0000-4000-8000-000000000013")}, "audit_mismatch"),
    ({"authorization": "incorrect"}, "not_authorized"),
])
def test_release_wrong_scope_rejected(held, override, expected):
    with pytest.raises(ValueError, match=expected):
        _release(held, **override)


def test_release_token_missing_rejected(held, monkeypatch):
    monkeypatch.delenv("NOTIFICATION_RECOVERY_RELEASE_TOKEN")
    with pytest.raises(ValueError, match="not_authorized"):
        _release(held)


@pytest.mark.parametrize("state,attempts,provider", [
    ("reserved", 1, None), ("reserved", 0, "provider-id"),
    ("ambiguous", 1, None), ("sending", 1, None),
])
def test_release_rejects_started_or_ambiguous_sends(held, state, attempts, provider):
    with session_scope(held["app"]) as session:
        log = session.get(NotificationLog, held["notification"])
        log.status, log.attempt_count, log.ses_message_id = state, attempts, provider
    with pytest.raises(ValueError, match="reservation_not_eligible"):
        _release(held)


def test_release_rechecks_n8n_evidence_and_recipient(held):
    with session_scope(held["app"]) as session:
        log = session.get(NotificationLog, held["notification"])
        user = session.get(User, log.user_id)
        log.recipient_alias = user.email
    with pytest.raises(ValueError, match="recipient_not_controlled"):
        _release(held)
    with session_scope(held["app"]) as session:
        log = session.get(NotificationLog, held["notification"])
        log.recipient_alias = "controlled@example.test"
    invalid = _evidence(held["run"], held["batch"], ses_seen=True)
    try:
        with pytest.raises(ValueError, match="ses_node_may_have_run"):
            release_recovery(held["app"], invalid, event_id=held["event"],
                             batch_id=held["batch"], notification_key=held["key"],
                             recovery_audit_id=held["audit"], authorization=RELEASE_TOKEN)
    finally:
        invalid.dispose()


def test_duplicate_and_concurrent_release_only_one_succeeds(held):
    def attempt(_: int) -> str:
        try:
            _release(held)
            return "released"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["rejected", "released"]
    with pytest.raises(ValueError, match="event_not_held"):
        _release(held)
    with session_scope(held["app"]) as session:
        assert session.scalar(select(func.count()).select_from(WorkflowExecution).where(
            WorkflowExecution.workflow_type == "outbox_reconcile")) == 2


def test_release_preserves_unrelated_event(held):
    with session_scope(held["app"]) as session:
        other = OutboxEvent(event_id=uuid.uuid4(), event_type="upload_batch.ready.v1",
                            aggregate_id=held["batch"], payload={"test": True},
                            # This tests scope isolation, not host/container clock agreement.
                            next_attempt_at=datetime.now(UTC) - timedelta(minutes=1))
        session.add(other)
        other_id = other.event_id
    _release(held)
    with session_scope(held["app"]) as session:
        other = session.get(OutboxEvent, other_id)
        assert other.status == "pending" and other.retry_count == 0
        assert "recovery_dispatch_scope" not in other.payload
    ordinary = claim_due(held["app"])
    assert ordinary is not None and ordinary["event_id"] == str(other_id)
    with session_scope(held["app"]) as session:
        assert session.get(OutboxEvent, held["event"]).status == "pending"


def test_claim_respects_due_boundary_and_targeted_scope(held, monkeypatch):
    from services.eligibility import dispatcher

    _release(held)
    with session_scope(held["app"]) as session:
        released = session.get(OutboxEvent, held["event"])
        boundary = released.next_attempt_at + timedelta(minutes=1)
        other = OutboxEvent(event_id=uuid.uuid4(), event_type="upload_batch.ready.v1",
                            aggregate_id=held["batch"], payload={"test": True},
                            next_attempt_at=boundary)
        session.add(other)
        other_id = other.event_id

    class Clock(datetime):
        current = boundary - timedelta(seconds=1)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(dispatcher, "datetime", Clock)
    # Targeted recovery is due but excluded; the ordinary event is not due yet.
    assert claim_due(held["app"]) is None
    with session_scope(held["app"]) as session:
        assert session.get(OutboxEvent, other_id).retry_count == 0
    Clock.current = boundary
    claimed = claim_due(held["app"])
    assert claimed is not None and claimed["event_id"] == str(other_id)
    with session_scope(held["app"]) as session:
        released = session.get(OutboxEvent, held["event"])
        assert released.status == "pending" and released.retry_count == 1
