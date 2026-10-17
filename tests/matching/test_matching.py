"""M5 correctness tests use a dedicated PostgreSQL database and synthetic rules only."""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from scripts.seed_matching_demo import SOURCE_ID, seed_synthetic
from services.common.db import make_engine, session_scope
from services.common.models import (
    LoanProduct,
    Match,
    OutboxEvent,
    UploadBatch,
    User,
    WorkflowExecution,
)
from services.eligibility.dispatcher import (
    claim_due,
    dispatch_once,
    finish_attempt,
    reconcile_stale,
)
from services.eligibility.gemini import advise
from services.eligibility.rules import ENGINE_VERSION, ProductFacts, UserFacts, evaluate
from services.eligibility.storage import (
    accept_event,
    candidate_page,
    complete_run,
    persist_page,
    reserve_llm_call,
)
from services.eligibility.transport import signature, verify


@pytest.fixture(scope="module")
def engine():
    name = os.environ["TEST_DB_NAME"].removesuffix("_test") + "_matching_test"
    assert name.endswith("_test") and name not in {os.environ["POSTGRES_DB"], os.environ["N8N_DB_NAME"]}
    old = os.environ.get("DATABASE_NAME")
    os.environ["DATABASE_NAME"] = name
    command.upgrade(Config("database/alembic.ini"), "head")
    db = make_engine(role="migration", database=name)
    yield db
    db.dispose()
    if old is None:
        os.environ.pop("DATABASE_NAME", None)
    else:
        os.environ["DATABASE_NAME"] = old


@pytest.fixture
def seeded(engine):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE notification_matches, notification_logs, matches, workflow_executions, outbox_events, upload_row_errors, users, upload_batches, loan_products, product_sources CASCADE"))
    seed_synthetic(engine)
    return engine


def facts(engine, key="demo-profile"):
    with session_scope(engine) as session:
        row = session.scalar(select(LoanProduct).where(LoanProduct.source_id == SOURCE_ID,
            LoanProduct.source_product_key == key))
        return ProductFacts(id=str(row.id), version=row.version, source_type="synthetic",
            is_current=True, verification_status="verified", retired=False,
            currency_code=row.currency_code, criterion_states=row.criterion_states,
            eligibility_rules=row.eligibility_rules)


def user(**changes):
    data = {"id": str(uuid.uuid4()), "batch_id": str(uuid.uuid4()), "monthly_income": Decimal(50000),
            "income_currency": "INR", "credit_score": 700, "age": 25,
            "employment_status": "salaried"}
    return UserFacts(**(data | changes))


def batch_with_event(engine, *, demo=True, income_currency=None, score=710, age=30,
                     employment="salaried"):
    batch_id = uuid.uuid4()
    event_id = uuid.uuid5(uuid.NAMESPACE_URL, f"upload_batch.ready.v1:{batch_id}")
    with session_scope(engine) as session:
        session.add(UploadBatch(id=batch_id, object_bucket="test", object_key=f"uploads/{batch_id}/test.csv",
            schema_version=1, status="processed", accepted_rows=1, total_rows=1, is_demo=demo))
        session.flush()
        session.add(User(id=uuid.uuid4(), upload_batch_id=batch_id, source_user_id="test-one",
            email="test@example.com", monthly_income=Decimal(50000), income_currency=income_currency,
            credit_score=score, age=age, employment_status=employment,
            employment_status_raw=employment))
        session.add(OutboxEvent(event_id=event_id, event_type="upload_batch.ready.v1",
            aggregate_id=batch_id, payload={"batch_id": str(batch_id)}))
    return batch_id, event_id


@pytest.mark.parametrize(("change", "expected"), [
    ({}, "ELIGIBLE_POTENTIAL"),
    ({"credit_score": 699}, "INELIGIBLE"),
    ({"age": 24}, "INELIGIBLE"),
    ({"employment_status": "self_employed"}, "INELIGIBLE"),
    ({"employment_status": "other"}, "INSUFFICIENT_DATA"),
    ({"credit_score": None}, "INSUFFICIENT_DATA"),
])
def test_rule_boundaries(seeded, change, expected):
    decision = evaluate(user(**change), facts(seeded), demo_batch=True)
    assert decision.status == expected
    assert decision.engine_version == ENGINE_VERSION and decision.reasons


def test_income_currency_and_hard_failure_priority(seeded):
    product = facts(seeded, "demo-inr")
    assert evaluate(user(monthly_income=Decimal("39999.99")), product, demo_batch=True).status == "INELIGIBLE"
    assert evaluate(user(monthly_income=Decimal(40000)), product, demo_batch=True).status == "ELIGIBLE_POTENTIAL"
    assert evaluate(user(income_currency="USD"), product, demo_batch=True).status == "INELIGIBLE"
    assert evaluate(user(income_currency=None), product, demo_batch=True).status == "INSUFFICIENT_DATA"
    assert evaluate(user(income_currency=None, credit_score=699), product, demo_batch=True).status == "INELIGIBLE"


def test_unknown_and_isolation(seeded, monkeypatch):
    product = facts(seeded)
    assert evaluate(user(), product, demo_batch=False).status != "ELIGIBLE_POTENTIAL"
    unknown = product.model_copy(update={"criterion_states": {"age": "UNKNOWN"}})
    decision = evaluate(user(), unknown, demo_batch=True)
    assert decision.status == "REVIEW_REQUIRED"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert advise(decision) == "unavailable"
    review = product.model_copy(update={"verification_status": "review_required"})
    assert evaluate(user(), review, demo_batch=True).status == "REVIEW_REQUIRED"


def test_advisory_invalid_output_and_budget(seeded, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    decision = evaluate(user(), facts(seeded).model_copy(update={"criterion_states": {"age": "UNKNOWN"}}),
                        demo_batch=True)
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": '{"status":"eligible"}'}]}}]},
    )))
    with client:
        assert advise(decision, client=client) == "invalid_response"
    batch_id, event_id = batch_with_event(seeded)
    run_id = uuid.UUID(accept_event(seeded, event_id=event_id, batch_id=batch_id)["run_id"])
    assert reserve_llm_call(seeded, run_id, 2)
    assert reserve_llm_call(seeded, run_id, 2)
    assert not reserve_llm_call(seeded, run_id, 2)


def test_sql_prefilter_and_completion_idempotency(seeded):
    batch_id, event_id = batch_with_event(seeded)
    accepted = accept_event(seeded, event_id=event_id, batch_id=batch_id)
    assert accepted["accepted"] is True
    run_id = uuid.UUID(accepted["run_id"])
    page = candidate_page(seeded, run_id, None)
    assert len(page["candidates"]) == 1  # INR product excluded because upload currency is unknown.
    pair = page["candidates"][0]
    raw = pair["user"]
    raw["monthly_income"] = Decimal(raw["monthly_income"])
    decision = evaluate(UserFacts.model_validate(raw), ProductFacts.model_validate(pair["product"]), demo_batch=True)
    assert decision.status == "ELIGIBLE_POTENTIAL"
    first = persist_page(seeded, run_id, None, page["next_cursor"], [decision])
    second = persist_page(seeded, run_id, None, page["next_cursor"], [decision])
    assert first["inserted"] == 1 and second["inserted"] == 0 and second["replayed"]
    assert complete_run(seeded, run_id, None)["status"] == "succeeded"
    assert complete_run(seeded, run_id, None)["status"] == "already_complete"
    assert accept_event(seeded, event_id=event_id, batch_id=batch_id)["state"] == "complete"
    with session_scope(seeded) as session:
        assert session.scalar(select(func.count()).select_from(Match)) == 1
        assert session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "matching.completed.v1")) == 1
        assert session.get(WorkflowExecution, run_id).metrics["candidates"] == 1


def test_persistence_rejects_forged_positive(seeded):
    batch_id, event_id = batch_with_event(seeded)
    run_id = uuid.UUID(accept_event(seeded, event_id=event_id, batch_id=batch_id)["run_id"])
    page = candidate_page(seeded, run_id, None)
    pair = page["candidates"][0]
    raw = dict(pair["user"])
    raw["monthly_income"] = Decimal(raw["monthly_income"])
    valid = evaluate(UserFacts.model_validate(raw), ProductFacts.model_validate(pair["product"]), demo_batch=True)
    forged = valid.model_copy(update={"decision_input_sha256": "0" * 64})
    with pytest.raises(ValueError, match="decision_provenance_mismatch"):
        persist_page(seeded, run_id, None, None, [forged])
    with session_scope(seeded) as session:
        assert session.scalar(select(func.count()).select_from(Match)) == 0


def test_real_products_cannot_auto_match(seeded):
    batch_id, event_id = batch_with_event(seeded, demo=False)
    run_id = uuid.UUID(accept_event(seeded, event_id=event_id, batch_id=batch_id)["run_id"])
    assert candidate_page(seeded, run_id, None)["candidates"] == []


def test_keyset_pages_are_bounded_and_complete(seeded):
    batch_id, event_id = batch_with_event(seeded)
    with session_scope(seeded) as session:
        batch = session.get(UploadBatch, batch_id)
        batch.accepted_rows = batch.total_rows = 25
        for number in range(24):
            session.add(User(id=uuid.uuid4(), upload_batch_id=batch_id,
                source_user_id=f"extra-{number}", email=f"extra-{number}@example.invalid",
                monthly_income=Decimal(50000), income_currency=None, credit_score=600,
                age=30, employment_status="salaried", employment_status_raw="Salaried"))
    run_id = uuid.UUID(accept_event(seeded, event_id=event_id, batch_id=batch_id)["run_id"])
    first = candidate_page(seeded, run_id, None)
    second = candidate_page(seeded, run_id, first["next_cursor"])
    assert first["next_cursor"] is not None and second["next_cursor"] is None
    assert len(first["candidates"]) + len(second["candidates"]) == 1


def test_signed_event_replay_window(monkeypatch):
    monkeypatch.setenv("MATCHING_WEBHOOK_SECRET", "t" * 40)
    import time
    body = {"event_id": str(uuid.uuid4()), "event_type": "upload_batch.ready.v1", "batch_id": str(uuid.uuid4())}
    timestamp = str(int(time.time()))
    headers = {"X-Loan-Event-Id": body["event_id"], "X-Loan-Timestamp": timestamp,
               "X-Loan-Signature": signature(body, timestamp, "t" * 40)}
    assert str(verify(body, headers).event_id) == body["event_id"]
    with pytest.raises(ValueError, match="signature"):
        verify(body, headers | {"X-Loan-Signature": "0" * 64})
    with pytest.raises(ValueError, match="expired"):
        verify(body, headers | {"X-Loan-Timestamp": str(int(timestamp) - 400)})


def test_dispatcher_retries_and_concurrent_claim(seeded, monkeypatch):
    from datetime import timedelta

    _, event_id = batch_with_event(seeded)
    with session_scope(seeded) as session:
        event = session.get(OutboxEvent, event_id)
        event.next_attempt_at = event.created_at - timedelta(seconds=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim_due(seeded), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    claim = next(claim for claim in claims if claim is not None)
    assert finish_attempt(seeded, event_id, claim["claim_expires_at"], delivered=False,
                          error_code="webhook_transport_or_response")
    with session_scope(seeded) as session:
        event = session.get(OutboxEvent, event_id)
        assert event.status == "pending" and event.retry_count == 1
        event.next_attempt_at = event.created_at - timedelta(seconds=1)
    monkeypatch.setenv("MATCHING_WEBHOOK_URL", "http://127.0.0.1:5678/webhook/loan-matching")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(202, json={
        "run_id": str(uuid.uuid4()), "batch_id": json.loads(request.content)["batch_id"],
    })))
    with client:
        assert dispatch_once(seeded, client=client) == "delivered"
    with session_scope(seeded) as session:
        assert session.get(OutboxEvent, event_id).status == "delivered"


def test_stalled_acknowledged_run_requeued(seeded):
    from datetime import UTC, datetime, timedelta

    batch_id, event_id = batch_with_event(seeded)
    run_id = uuid.UUID(accept_event(seeded, event_id=event_id, batch_id=batch_id)["run_id"])
    with session_scope(seeded) as session:
        run = session.get(WorkflowExecution, run_id)
        run.metrics = {**run.metrics, "heartbeat_at": (datetime.now(UTC) - timedelta(minutes=20)).isoformat()}
        session.get(OutboxEvent, event_id).status = "delivered"
    assert reconcile_stale(seeded) == 1
    with session_scope(seeded) as session:
        assert session.get(OutboxEvent, event_id).status == "pending"


def test_workflow_contract_no_secret():
    raw = (Path(__file__).resolve().parents[2] / "workflows/matching.json").read_text()
    workflow = json.loads(raw)
    names = {node["name"] for node in workflow["nodes"]}
    assert {"Signed Matching Webhook", "Authenticate and Claim Event", "SQL Candidate Prefilter",
            "Deterministic Rule Evaluation", "Selective Gemini Advisory", "Persist Potential Matches",
            "Commit Completion Event"} <= names
    assert "MATCHING_WEBHOOK_SECRET" not in raw
