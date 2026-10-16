"""Operator-only, event-specific preparation; never dispatches or sends."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine

from services.common.db import session_scope
from services.common.models import (
    LoanProduct,
    Match,
    NotificationLog,
    NotificationMatch,
    OutboxEvent,
    ProductSource,
    UploadBatch,
    User,
    WorkflowExecution,
)
from services.notifications.content import idempotency_key

WORKFLOW_ID = "loanNotificationsM6"
ACCEPT_NODE = "Authenticate and Durably Accept Event"
PREFLIGHT_NODE = "Enforce Test Recipient and Begin Attempt"
SES_NODE = "AWS SES Send to Controlled Test Inbox"
STALE_AFTER = timedelta(minutes=15)
# Preparation cannot make an event dispatchable. A separate authorized release
# must review and change this deadline before any targeted dispatcher run.
HOLD_UNTIL = datetime(9999, 12, 31, tzinfo=UTC)


def _reference(values: list[Any], value: Any) -> Any:
    if not isinstance(value, str) or not value.isdecimal() or int(value) >= len(values):
        raise ValueError("n8n_evidence_invalid")
    return values[int(value)]


def _n8n_failed_before_ses(n8n_engine: Engine, execution_id: int, *,
                           run_id: uuid.UUID, batch_id: uuid.UUID) -> None:
    if execution_id <= 0:
        raise ValueError("n8n_execution_id_invalid")
    with n8n_engine.connect() as connection:
        if n8n_engine.dialect.name == "postgresql":
            connection.execute(text("SET TRANSACTION READ ONLY"))
        row = connection.execute(text('SELECT e."workflowId", e.status, e."stoppedAt", d.data '
                                      'FROM execution_entity e JOIN execution_data d '
                                      'ON d."executionId" = e.id WHERE e.id = :execution_id'),
                                 {"execution_id": execution_id}).mappings().one_or_none()
    if row is None or row["workflowId"] != WORKFLOW_ID or row["status"] != "error" or row["stoppedAt"] is None:
        raise ValueError("n8n_execution_not_terminal_failure")
    try:
        values = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        result = _reference(values, values[0]["resultData"])
        run_data = _reference(values, result["runData"])
        if SES_NODE in run_data or PREFLIGHT_NODE not in run_data:
            raise ValueError("ses_node_may_have_run")
        preflight_runs = _reference(values, run_data[PREFLIGHT_NODE])
        preflight = _reference(values, preflight_runs[0])
        if "error" not in preflight:
            raise ValueError("preflight_failure_not_proven")
        accepted_runs = _reference(values, run_data[ACCEPT_NODE])
        accepted = _reference(values, accepted_runs[0])
        main = _reference(values, _reference(values, accepted["data"])["main"])
        items = _reference(values, main[0])
        payload = _reference(values, _reference(values, items[0])["json"])
        observed_run = _reference(values, payload["run_id"])
        observed_batch = _reference(values, payload["batch_id"])
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("n8n_evidence_invalid") from error
    if observed_run != str(run_id) or observed_batch != str(batch_id):
        raise ValueError("n8n_execution_scope_mismatch")


def prepare_recovery(app_engine: Engine, n8n_engine: Engine, *, event_id: uuid.UUID,
                     batch_id: uuid.UUID, notification_key: str, n8n_execution_id: int,
                     authorization: str) -> uuid.UUID:
    """Hold one proven-unsent reservation for future, separately authorized release.

    This does not call a webhook or provider. It leaves the original notification
    untouched and moves only the exact event to a non-due, audited pending state.
    """
    expected_authorization = os.environ.get("NOTIFICATION_RECOVERY_TOKEN", "")
    if (len(expected_authorization) < 32 or len(authorization) < 32 or
            not compare_digest(authorization, expected_authorization)):
        raise ValueError("recovery_not_authorized")
    if os.environ.get("NOTIFICATION_MODE") != "test" or os.environ.get("NOTIFICATION_TRANSPORT") != "mock" or \
            os.environ.get("NOTIFICATION_SES_ENABLED") != "0" or \
            os.environ.get("NOTIFICATION_SES_MAX_ATTEMPTS") != "0":
        raise ValueError("recovery_requires_safe_mock_mode")
    now = datetime.now(UTC)
    with session_scope(app_engine) as session:
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.event_id == event_id)
                               .with_for_update())
        if (event is None or event.aggregate_id != batch_id or
                event.event_type != "matching.completed.v1" or event.status != "delivered" or
                event.retry_count < 1 or event.claimed_at is not None or
                event.claim_expires_at is not None):
            raise ValueError("recovery_event_not_eligible")
        batch = session.get(UploadBatch, batch_id)
        if batch is None or not batch.is_demo or batch.status != "matched":
            raise ValueError("recovery_batch_not_eligible")
        run = session.scalar(select(WorkflowExecution).where(
            WorkflowExecution.event_id == event_id).with_for_update())
        if (run is None or run.workflow_type != "notification" or
                run.upload_batch_id != batch_id or run.status != "running" or
                run.metrics.get("cursor") is not None):
            raise ValueError("recovery_run_not_eligible")
        try:
            heartbeat = datetime.fromisoformat(run.metrics["heartbeat_at"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("recovery_heartbeat_invalid") from error
        if heartbeat.tzinfo is None or heartbeat > now - STALE_AFTER:
            raise ValueError("recovery_run_not_stale")
        logs = session.scalars(select(NotificationLog).where(
            NotificationLog.workflow_execution_id == run.id).with_for_update()).all()
        if len(logs) != 1:
            raise ValueError("recovery_reservation_count_invalid")
        log = logs[0]
        if (log.status != "reserved" or log.attempt_count != 0 or
                log.ses_message_id is not None or log.last_attempt_at is not None or
                log.delivery_mode != "ses" or
                not compare_digest(notification_key, idempotency_key(batch_id, log.user_id)) or
                not compare_digest(notification_key, log.idempotency_key)):
            raise ValueError("recovery_reservation_not_eligible")
        controlled = os.environ.get("NOTIFICATION_TEST_EMAIL", "").strip().lower()
        user = session.get(User, log.user_id)
        if (user is None or user.upload_batch_id != batch_id or not controlled or
                log.recipient_alias != controlled or log.recipient_alias == user.email):
            raise ValueError("recovery_recipient_not_controlled")
        links = session.execute(select(NotificationMatch, Match, LoanProduct, ProductSource).join(
            Match, NotificationMatch.match_id == Match.id).join(
            LoanProduct, Match.product_id == LoanProduct.id).join(
            ProductSource, LoanProduct.source_id == ProductSource.id).where(
            NotificationMatch.notification_id == log.id)).all()
        if (len(links) != 1 or links[0][1].user_id != user.id or
                links[0][1].status != "potential" or
                links[0][2].verification_status != "verified" or
                links[0][3].source_type != "synthetic" or
                session.scalar(select(func.count()).select_from(User).where(
                    User.upload_batch_id == batch_id)) != 1 or
                session.scalar(select(func.count()).select_from(Match).join(
                    User, Match.user_id == User.id).where(
                    User.upload_batch_id == batch_id, Match.status == "potential")) != 1):
            raise ValueError("recovery_demo_scope_invalid")
        # Terminal n8n evidence is immutable; require its accepted output to
        # identify this exact application run and batch, and no SES runData.
        _n8n_failed_before_ses(n8n_engine, n8n_execution_id,
                               run_id=run.id, batch_id=batch_id)
        audit = WorkflowExecution(
            id=uuid.uuid4(), workflow_type="outbox_reconcile", status="succeeded",
            parent_execution_id=run.id, upload_batch_id=batch_id,
            started_at=now, finished_at=now,
            metrics={"action": "manual_notification_recovery_prepared",
                     "event_id": str(event_id), "notification_id": str(log.id),
                     "n8n_execution_id": n8n_execution_id,
                     "prior_retry_count": event.retry_count,
                     "hold_until": HOLD_UNTIL.isoformat()},
        )
        session.add(audit)
        event.status = "pending"
        event.next_attempt_at = HOLD_UNTIL
        event.last_error_code = "manual_recovery_held"
        session.flush()
        return audit.id


def release_recovery(app_engine: Engine, n8n_engine: Engine, *, event_id: uuid.UUID,
                     batch_id: uuid.UUID, notification_key: str,
                     recovery_audit_id: uuid.UUID, authorization: str) -> uuid.UUID:
    """Audit and release one held event for *targeted* dispatch, without dispatching it."""
    expected = os.environ.get("NOTIFICATION_RECOVERY_RELEASE_TOKEN", "")
    if len(expected) < 32 or len(authorization) < 32 or not compare_digest(authorization, expected):
        raise ValueError("release_not_authorized")
    if (os.environ.get("NOTIFICATION_MODE") != "test" or
            os.environ.get("NOTIFICATION_TRANSPORT") != "mock" or
            os.environ.get("NOTIFICATION_SES_ENABLED") != "0" or
            os.environ.get("NOTIFICATION_SES_MAX_ATTEMPTS") != "0"):
        raise ValueError("release_requires_safe_mock_mode")

    now = datetime.now(UTC)
    with session_scope(app_engine) as session:
        event = session.scalar(select(OutboxEvent).where(
            OutboxEvent.event_id == event_id).with_for_update())
        if (event is None or event.aggregate_id != batch_id or
                event.event_type != "matching.completed.v1" or event.status != "pending" or
                event.next_attempt_at != HOLD_UNTIL or
                event.last_error_code != "manual_recovery_held" or
                event.claimed_at is not None or event.claim_expires_at is not None or
                event.payload.get("recovery_dispatch_scope") is not None):
            raise ValueError("release_event_not_held")
        audit = session.scalar(select(WorkflowExecution).where(
            WorkflowExecution.id == recovery_audit_id).with_for_update())
        if (audit is None or audit.workflow_type != "outbox_reconcile" or
                audit.status != "succeeded" or audit.upload_batch_id != batch_id or
                audit.metrics.get("action") != "manual_notification_recovery_prepared" or
                audit.metrics.get("event_id") != str(event_id) or
                audit.metrics.get("hold_until") != HOLD_UNTIL.isoformat()):
            raise ValueError("release_audit_mismatch")
        run = session.scalar(select(WorkflowExecution).where(
            WorkflowExecution.event_id == event_id).with_for_update())
        if (run is None or audit.parent_execution_id != run.id or
                run.workflow_type != "notification" or run.upload_batch_id != batch_id or
                run.status != "running" or run.metrics.get("cursor") is not None):
            raise ValueError("release_run_mismatch")
        logs = session.scalars(select(NotificationLog).where(
            NotificationLog.workflow_execution_id == run.id).with_for_update()).all()
        if len(logs) != 1:
            raise ValueError("release_reservation_count_invalid")
        log = logs[0]
        if (audit.metrics.get("notification_id") != str(log.id) or
                log.status != "reserved" or log.attempt_count != 0 or
                log.last_attempt_at is not None or log.ses_message_id is not None or
                log.delivery_mode != "ses" or
                not compare_digest(notification_key, idempotency_key(batch_id, log.user_id)) or
                not compare_digest(notification_key, log.idempotency_key)):
            raise ValueError("release_reservation_not_eligible")
        controlled = os.environ.get("NOTIFICATION_TEST_EMAIL", "").strip().lower()
        user = session.get(User, log.user_id)
        batch = session.get(UploadBatch, batch_id)
        if (batch is None or not batch.is_demo or batch.status != "matched" or
                user is None or user.upload_batch_id != batch_id or not controlled or
                log.recipient_alias != controlled or log.recipient_alias == user.email):
            raise ValueError("release_recipient_not_controlled")
        links = session.execute(select(NotificationMatch, Match, LoanProduct, ProductSource).join(
            Match, NotificationMatch.match_id == Match.id).join(
            LoanProduct, Match.product_id == LoanProduct.id).join(
            ProductSource, LoanProduct.source_id == ProductSource.id).where(
            NotificationMatch.notification_id == log.id)).all()
        if (len(links) != 1 or links[0][1].user_id != user.id or
                links[0][1].status != "potential" or
                links[0][2].verification_status != "verified" or
                links[0][3].source_type != "synthetic"):
            raise ValueError("release_demo_scope_invalid")
        execution_id = audit.metrics.get("n8n_execution_id")
        if not isinstance(execution_id, int):
            raise TypeError("release_n8n_evidence_invalid")
        _n8n_failed_before_ses(n8n_engine, execution_id, run_id=run.id, batch_id=batch_id)

        release_audit = WorkflowExecution(
            id=uuid.uuid4(), workflow_type="outbox_reconcile", status="succeeded",
            parent_execution_id=run.id, upload_batch_id=batch_id,
            started_at=now, finished_at=now,
            metrics={"action": "manual_notification_recovery_released",
                     "event_id": str(event_id), "notification_id": str(log.id),
                     "preparation_audit_id": str(recovery_audit_id),
                     "dispatch_scope": "targeted_only"},
        )
        session.add(release_audit)
        event.payload = {**event.payload, "recovery_dispatch_scope": "targeted_only"}
        event.next_attempt_at = now
        event.last_error_code = "manual_recovery_released"
        session.flush()
        return release_audit.id
