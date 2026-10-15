"""Small transactional stages for Workflow C; n8n owns sequencing and SES."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
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
from services.notifications.content import (
    TEMPLATE_VERSION,
    idempotency_key,
    recipient_for,
    render,
    transport_mode,
)


def accept_event(engine: Engine, *, event_id: uuid.UUID, batch_id: uuid.UUID) -> dict[str, Any]:
    now = datetime.now(UTC)
    with session_scope(engine) as session:
        event = session.get(OutboxEvent, event_id)
        if event is None or event.event_type != "matching.completed.v1" or event.aggregate_id != batch_id:
            raise ValueError("unknown_completion_event")
        batch = session.get(UploadBatch, batch_id)
        if batch is None or batch.status != "matched":
            raise ValueError("matching_not_complete")
        matching_id = event.payload.get("matching_run_id")
        try:
            parent = session.get(WorkflowExecution, uuid.UUID(str(matching_id)))
        except (ValueError, TypeError) as error:
            raise ValueError("matching_execution_missing") from error
        if parent is None or parent.workflow_type != "matching" or parent.status != "succeeded" or parent.upload_batch_id != batch_id:
            raise ValueError("matching_execution_missing")
        run = session.scalar(select(WorkflowExecution).where(WorkflowExecution.event_id == event_id).with_for_update())
        if run is not None:
            heartbeat = run.metrics.get("heartbeat_at")
            stale = not heartbeat or datetime.fromisoformat(heartbeat) < now - timedelta(minutes=15)
            accepted = run.status != "succeeded" and stale
            if accepted:
                run.metrics = {**run.metrics, "heartbeat_at": now.isoformat()}
            return {"run_id": str(run.id), "batch_id": str(batch_id), "accepted": accepted,
                    "state": run.status}
        run = WorkflowExecution(event_id=event_id, parent_execution_id=parent.id,
                                workflow_type="notification", upload_batch_id=batch_id,
                                status="running", metrics={"cursor": None, "mocked": 0, "sent": 0,
                                                           "ambiguous": 0, "heartbeat_at": now.isoformat()})
        session.add(run)
        session.flush()
        return {"run_id": str(run.id), "batch_id": str(batch_id), "accepted": True,
                "state": "running"}


def _products(session, user_id: uuid.UUID) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    rows = session.execute(select(Match, LoanProduct, ProductSource).join(
        LoanProduct, Match.product_id == LoanProduct.id).join(
        ProductSource, LoanProduct.source_id == ProductSource.id).outerjoin(
        NotificationMatch, NotificationMatch.match_id == Match.id).where(
        Match.user_id == user_id, Match.status == "potential", Match.notified_at.is_(None),
        NotificationMatch.match_id.is_(None), LoanProduct.verification_status == "verified",
        LoanProduct.retired_at.is_(None)).order_by(Match.id)).all()
    return [{"match_id": match.id, "institution": source.name, "name": product.product_name,
             "source_url": product.source_url, "source_type": source.source_type,
             "rate": (product.interest_rate_text or
                      (f"{product.interest_rate_min_pct}%" if product.interest_rate_min_pct is not None else None))}
            for match, product, source in rows]


def next_reservation(engine: Engine, run_id: uuid.UUID) -> dict[str, Any]:
    with session_scope(engine) as session:
        run = session.scalar(select(WorkflowExecution).where(WorkflowExecution.id == run_id).with_for_update())
        if run is None or run.workflow_type != "notification" or run.status != "running":
            raise ValueError("notification_run_not_running")
        batch = session.get(UploadBatch, run.upload_batch_id)
        if batch is None:
            raise ValueError("notification_batch_missing")
        cursor = run.metrics.get("cursor")
        query = select(User.id).join(Match, Match.user_id == User.id).where(
            User.upload_batch_id == batch.id, Match.status == "potential")
        if cursor:
            query = query.where(User.id > uuid.UUID(cursor))
        user_id = session.scalar(query.distinct().order_by(User.id).limit(1))
        if user_id is None:
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
            return {"run_id": str(run_id), "done": True, "metrics": run.metrics}
        key = idempotency_key(batch.id, user_id)
        log = session.scalar(select(NotificationLog).where(NotificationLog.idempotency_key == key).with_for_update())
        if log is not None:
            if log.status == "reserved":
                return {"run_id": str(run_id), "done": False, "notification_id": str(log.id),
                        "user_id": str(user_id), "state": "reserved"}
            if log.status == "sending":
                log.status = "ambiguous"  # Crash window: provider may already have accepted.
                log.last_error_code = "interrupted_after_send_started"
                run.metrics = {**run.metrics, "cursor": str(user_id),
                               "ambiguous": int(run.metrics.get("ambiguous", 0)) + 1,
                               "heartbeat_at": datetime.now(UTC).isoformat()}
                return {"run_id": str(run_id), "done": False, "skip": True, "state": "ambiguous"}
            run.metrics = {**run.metrics, "cursor": str(user_id),
                           "heartbeat_at": datetime.now(UTC).isoformat()}
            return {"run_id": str(run_id), "done": False, "skip": True, "state": log.status}
        products = _products(session, user_id)
        if not products:
            run.metrics = {**run.metrics, "cursor": str(user_id),
                           "heartbeat_at": datetime.now(UTC).isoformat()}
            return {"run_id": str(run_id), "done": False, "skip": True, "state": "no_new_matches"}
        if any(item["source_type"] == "synthetic" for item in products) and not batch.is_demo:
            raise ValueError("synthetic_match_in_real_batch")
        mode = transport_mode()
        log = NotificationLog(id=uuid.uuid4(), workflow_execution_id=run.id, user_id=user_id,
                              idempotency_key=key, recipient_alias=recipient_for(user_id),
                              template_version=TEMPLATE_VERSION, delivery_mode=mode, status="reserved")
        session.add(log)
        session.flush()
        for item in products:
            session.add(NotificationMatch(notification_id=log.id, match_id=item["match_id"]))
        return {"run_id": str(run_id), "done": False, "notification_id": str(log.id),
                "user_id": str(user_id), "state": "reserved", "match_count": len(products)}


def compose(engine: Engine, notification_id: uuid.UUID, *, begin_send: bool) -> dict[str, Any]:
    with session_scope(engine) as session:
        log = session.scalar(select(NotificationLog).where(NotificationLog.id == notification_id).with_for_update())
        if log is None or log.status != "reserved":
            raise ValueError("notification_not_reserved")
        run = session.get(WorkflowExecution, log.workflow_execution_id)
        batch = session.get(UploadBatch, run.upload_batch_id) if run else None
        if batch is None or run is None or run.status != "running" or log.recipient_alias != recipient_for(log.user_id):
            raise ValueError("recipient_policy_violation")
        if log.delivery_mode != transport_mode():
            raise ValueError("transport_changed_after_reservation")
        products = _products_for_log(session, log.id)
        if not products or (any(p["source_type"] == "synthetic" for p in products) and not batch.is_demo):
            raise ValueError("notification_matches_invalid")
        content = render(products, synthetic=all(p["source_type"] == "synthetic" for p in products))
        if begin_send:
            log.status = "sending"
            log.attempt_count += 1
            log.last_attempt_at = datetime.now(UTC)
            if log.attempt_count > 1:
                raise ValueError("notification_retry_limit")
        return {"run_id": str(run.id), "notification_id": str(log.id), "user_id": str(log.user_id),
                "recipient": log.recipient_alias, "delivery_mode": log.delivery_mode,
                "sender": os_sender() if begin_send else None, **content}


def os_sender() -> str:
    import os
    return os.environ.get("NOTIFICATION_FROM_EMAIL", "")


def _products_for_log(session, notification_id: uuid.UUID) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    rows = session.execute(select(LoanProduct, ProductSource).join(
        Match, Match.product_id == LoanProduct.id).join(
        NotificationMatch, NotificationMatch.match_id == Match.id).join(
        ProductSource, ProductSource.id == LoanProduct.source_id).where(
        NotificationMatch.notification_id == notification_id, Match.status == "potential",
        LoanProduct.verification_status == "verified", LoanProduct.retired_at.is_(None)).order_by(LoanProduct.id)).all()
    return [{"institution": source.name, "name": product.product_name,
             "source_url": product.source_url, "source_type": source.source_type,
             "rate": (product.interest_rate_text or
                      (f"{product.interest_rate_min_pct}%" if product.interest_rate_min_pct is not None else None))}
            for product, source in rows]


def mock_send(engine: Engine, notification_id: uuid.UUID, recipient: str) -> dict[str, str]:
    with session_scope(engine) as session:
        log = session.get(NotificationLog, notification_id)
        if log is None or log.status != "sending" or log.delivery_mode != "mock" or \
                transport_mode() != "mock" or recipient != recipient_for(log.user_id) or recipient != log.recipient_alias:
            raise ValueError("mock_recipient_policy_violation")
    return {"message_id": f"mock-{notification_id}", "notification_id": str(notification_id)}


def record_result(engine: Engine, notification_id: uuid.UUID, *, message_id: str | None,
                  error_code: str | None = None) -> dict[str, Any]:
    with session_scope(engine) as session:
        log = session.scalar(select(NotificationLog).where(NotificationLog.id == notification_id).with_for_update())
        if log is None or log.status != "sending":
            raise ValueError("notification_not_sending")
        run = session.scalar(select(WorkflowExecution).where(WorkflowExecution.id == log.workflow_execution_id).with_for_update())
        if run is None or run.status != "running":
            raise ValueError("notification_run_not_running")
        if log.delivery_mode == "ses" and message_id and not error_code:
            log.status = "sent"  # SES accepted the request; inbox delivery is not established.
            log.ses_message_id = message_id
            log.sent_at = datetime.now(UTC)
            for link in log.match_links:
                match = session.get(Match, link.match_id)
                if match is not None:
                    match.notified_at = log.sent_at
        elif log.delivery_mode == "mock" and message_id == f"mock-{log.id}" and not error_code:
            log.status = "mocked"
        else:
            log.status = "ambiguous" if log.delivery_mode == "ses" else "failed"
            log.last_error_code = (error_code or "provider_response_missing")[:80]
        run.metrics = {**run.metrics, "cursor": str(log.user_id),
                       log.status: int(run.metrics.get(log.status, 0)) + 1,
                       "heartbeat_at": datetime.now(UTC).isoformat()}
        return {"run_id": str(run.id), "notification_id": str(log.id), "state": log.status}
