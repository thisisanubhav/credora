"""Short PostgreSQL transactions for accepted events, pages, and completion."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from services.common.db import session_scope
from services.common.models import (
    LoanProduct,
    Match,
    OutboxEvent,
    ProductSource,
    UploadBatch,
    User,
    WorkflowExecution,
)
from services.eligibility.rules import Decision, ProductFacts, UserFacts, evaluate

PREFILTER_SQL = (Path(__file__).parent / "sql" / "prefilter.sql").read_text(encoding="utf-8")
PAGE_SIZE = 20  # At 50 products this transfers at most 1,000 pair records per step.
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def reserve_llm_call(engine: Engine, run_id: uuid.UUID, limit: int) -> bool:
    with session_scope(engine) as session:
        run = session.scalar(select(WorkflowExecution).where(WorkflowExecution.id == run_id).with_for_update())
        if run is None or run.status != "running":
            return False
        metrics = dict(run.metrics)
        used = int(metrics.get("llm_calls", 0))
        if used >= limit:
            return False
        metrics["llm_calls"] = used + 1
        run.metrics = metrics
        return True


def accept_event(engine: Engine, *, event_id: uuid.UUID, batch_id: uuid.UUID) -> dict[str, Any]:
    now = datetime.now(UTC)
    with session_scope(engine) as session:
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.event_id == event_id,
            OutboxEvent.aggregate_id == batch_id, OutboxEvent.event_type == "upload_batch.ready.v1"))
        batch = session.scalar(select(UploadBatch).where(UploadBatch.id == batch_id).with_for_update())
        if event is None or batch is None or batch.accepted_rows == 0:
            raise ValueError("unknown_ready_event")
        existing = session.scalar(select(WorkflowExecution).where(WorkflowExecution.event_id == event_id).with_for_update())
        if existing is not None:
            if existing.status == "succeeded":
                return {"accepted": False, "state": "complete", "run_id": str(existing.id), "batch_id": str(batch_id)}
            heartbeat = existing.metrics.get("heartbeat_at")
            if existing.status == "running" and heartbeat:
                last = datetime.fromisoformat(heartbeat)
                if last > now - timedelta(minutes=15):
                    return {"accepted": False, "state": "running", "run_id": str(existing.id), "batch_id": str(batch_id)}
            existing.status = "running"
            existing.error_code = None
            metrics = dict(existing.metrics)
            metrics["heartbeat_at"] = now.isoformat()
            existing.metrics = metrics
            batch.status = "matching"
            return {"accepted": True, "state": "resumed", "run_id": str(existing.id), "batch_id": str(batch_id)}
        if batch.status not in {"processed", "processed_with_errors", "matching", "match_failed", "matched"}:
            raise ValueError("batch_not_ready")
        run = WorkflowExecution(event_id=event_id, workflow_type="matching", upload_batch_id=batch_id,
            status="running", metrics={"heartbeat_at": now.isoformat(), "pages": {}, "candidates": 0,
                                        "potential": 0, "ineligible": 0, "review_required": 0,
                                        "insufficient_data": 0, "llm_calls": 0, "inserted_matches": 0})
        session.add(run)
        session.flush()
        batch.status = "matching"
        return {"accepted": True, "state": "new", "run_id": str(run.id), "batch_id": str(batch_id)}


def batch_summary(engine: Engine, run_id: uuid.UUID) -> dict[str, Any]:
    with session_scope(engine) as session:
        run = session.get(WorkflowExecution, run_id)
        if run is None or run.workflow_type != "matching":
            raise ValueError("unknown_matching_run")
        batch = session.get(UploadBatch, run.upload_batch_id)
        if batch is None:
            raise ValueError("matching_batch_missing")
        product_count = session.scalar(select(func.count()).select_from(LoanProduct).where(
            LoanProduct.is_current.is_(True), LoanProduct.verification_status == "verified",
            LoanProduct.retired_at.is_(None))) or 0
        return {"run_id": str(run_id), "batch_id": str(batch.id), "demo_batch": batch.is_demo,
                "user_count": batch.accepted_rows, "verified_product_count": product_count,
                "theoretical_pairs": batch.accepted_rows * product_count}


def candidate_page(engine: Engine, run_id: uuid.UUID, cursor: str | None) -> dict[str, Any]:
    with session_scope(engine) as session:
        run = session.get(WorkflowExecution, run_id)
        if run is None or run.workflow_type != "matching" or run.status != "running":
            raise ValueError("matching_run_not_active")
        batch = session.get(UploadBatch, run.upload_batch_id)
        if batch is None:
            raise ValueError("matching_batch_missing")
        if cursor:
            cursor_user = uuid.UUID(cursor)
        else:
            cursor_user = uuid.UUID(ZERO_UUID)
        user_ids = session.scalars(select(User.id).where(
            User.upload_batch_id == batch.id, User.id > cursor_user,
        ).order_by(User.id).limit(PAGE_SIZE + 1)).all()
        selected_ids = user_ids[:PAGE_SIZE]
        next_cursor = str(selected_ids[-1]) if len(user_ids) > PAGE_SIZE else None
        rows = session.execute(text(PREFILTER_SQL), {
            "batch_id": batch.id, "demo_batch": batch.is_demo,
            "user_ids": selected_ids or [uuid.UUID(ZERO_UUID)],
        }).mappings().all()
        candidates = [{"user": {
            "id": str(row["user_id"]), "batch_id": str(row["batch_id"]),
            "monthly_income": str(row["monthly_income"]), "income_currency": row["income_currency"],
            "credit_score": row["credit_score"], "age": row["age"],
            "employment_status": row["employment_status"],
        }, "product": {
            "id": str(row["product_id"]), "version": row["version"],
            "source_type": row["source_type"], "is_current": row["is_current"],
            "verification_status": row["verification_status"], "retired": row["retired"],
            "currency_code": row["currency_code"], "criterion_states": row["criterion_states"],
            "eligibility_rules": row["eligibility_rules"],
        }} for row in rows]
        return {"run_id": str(run_id), "batch_id": str(batch.id), "demo_batch": batch.is_demo,
                "cursor": cursor, "next_cursor": next_cursor, "candidates": candidates}


def persist_page(engine: Engine, run_id: uuid.UUID, cursor: str | None,
                 next_cursor: str | None, decisions: list[Decision]) -> dict[str, Any]:
    page_key = cursor or "first"
    with session_scope(engine) as session:
        run = session.scalar(select(WorkflowExecution).where(WorkflowExecution.id == run_id).with_for_update())
        if run is None or run.workflow_type != "matching" or run.status != "running":
            raise ValueError("matching_run_not_active")
        metrics = dict(run.metrics)
        pages = dict(metrics.get("pages", {}))
        if page_key in pages:
            return {"run_id": str(run_id), "cursor": cursor, "next_cursor": pages[page_key], "inserted": 0, "replayed": True}
        inserted = 0
        potential = [item for item in decisions if item.status == "ELIGIBLE_POTENTIAL"]
        batch = session.get(UploadBatch, run.upload_batch_id)
        if batch is None:
            raise ValueError("matching_batch_missing")
        users = {item.id: item for item in session.scalars(select(User).where(
            User.upload_batch_id == run.upload_batch_id,
            User.id.in_([uuid.UUID(item.user_id) for item in potential]),
        )).all()}
        products = {product.id: (product, source_type) for product, source_type in session.execute(
            select(LoanProduct, ProductSource.source_type).join(
                ProductSource, ProductSource.id == LoanProduct.source_id,
            ).where(LoanProduct.id.in_([uuid.UUID(item.product_id) for item in potential]),
                    LoanProduct.is_current.is_(True),
                    LoanProduct.verification_status == "verified", LoanProduct.retired_at.is_(None)),
        ).all()}
        values = []
        for decision in decisions:
            if decision.batch_id != str(run.upload_batch_id):
                raise ValueError("decision_batch_mismatch")
            if decision.status == "ELIGIBLE_POTENTIAL":
                user = users.get(uuid.UUID(decision.user_id))
                found = products.get(uuid.UUID(decision.product_id))
                if user is None or found is None:
                    raise ValueError("decision_reference_not_matchable")
                product, source_type = found
                original = evaluate(UserFacts(id=str(user.id), batch_id=str(user.upload_batch_id),
                    monthly_income=user.monthly_income, income_currency=user.income_currency,
                    credit_score=user.credit_score, age=user.age, employment_status=user.employment_status),
                    ProductFacts(id=str(product.id), version=product.version, source_type=source_type,
                    is_current=product.is_current, verification_status=product.verification_status,
                    retired=False, currency_code=product.currency_code,
                    criterion_states=product.criterion_states, eligibility_rules=product.eligibility_rules),
                    demo_batch=batch.is_demo)
                if (original.status != "ELIGIBLE_POTENTIAL" or original.decision_input_sha256 != decision.decision_input_sha256
                        or product.version != decision.product_version or decision.llm_involved):
                    raise ValueError("decision_provenance_mismatch")
                values.append({"id": uuid.uuid4(), "user_id": user.id, "product_id": product.id,
                    "workflow_execution_id": run.id, "status": "potential", "evaluation_method": "deterministic",
                    "qualification_reasons": original.reasons + [{"code": original.engine_version, "outcome": "engine"}],
                    "decision_input_sha256": original.decision_input_sha256})
        if values:
            result = session.execute(insert(Match).values(values).on_conflict_do_nothing(
                constraint="uq_matches_user_product_version").returning(Match.id))
            inserted = len(result.scalars().all())
        pages[page_key] = next_cursor
        metrics["pages"] = pages
        metrics["heartbeat_at"] = datetime.now(UTC).isoformat()
        metrics["candidates"] = int(metrics.get("candidates", 0)) + len(decisions)
        for status, key in (("ELIGIBLE_POTENTIAL", "potential"), ("INELIGIBLE", "ineligible"),
                            ("REVIEW_REQUIRED", "review_required"), ("INSUFFICIENT_DATA", "insufficient_data")):
            metrics[key] = int(metrics.get(key, 0)) + sum(item.status == status for item in decisions)
        metrics["inserted_matches"] = int(metrics.get("inserted_matches", 0)) + inserted
        run.metrics = metrics
        return {"run_id": str(run_id), "cursor": cursor, "next_cursor": next_cursor, "inserted": inserted, "replayed": False}


def complete_run(engine: Engine, run_id: uuid.UUID, cursor: str | None) -> dict[str, Any]:
    with session_scope(engine) as session:
        run = session.scalar(select(WorkflowExecution).where(WorkflowExecution.id == run_id).with_for_update())
        if run is None or run.workflow_type != "matching":
            raise ValueError("unknown_matching_run")
        if run.status == "succeeded":
            return {"run_id": str(run_id), "status": "already_complete", "metrics": run.metrics}
        pages = run.metrics.get("pages", {})
        if run.status != "running" or (cursor or "first") not in pages or pages[cursor or "first"] is not None:
            raise ValueError("matching_pages_incomplete")
        batch = session.get(UploadBatch, run.upload_batch_id)
        if batch is None:
            raise ValueError("matching_batch_missing")
        batch.status = "matched"
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        session.execute(insert(OutboxEvent).values(
            event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"matching.completed.v1:{batch.id}"),
            event_type="matching.completed.v1", aggregate_id=batch.id,
            payload={"batch_id": str(batch.id), "matching_run_id": str(run.id),
                     "new_matches": run.metrics.get("inserted_matches", 0)},
        ).on_conflict_do_nothing(constraint="uq_outbox_events_aggregate_type"))
        return {"run_id": str(run_id), "status": "succeeded", "metrics": run.metrics}
