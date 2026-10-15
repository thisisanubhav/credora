"""Notification safety and persistence tests on a dedicated PostgreSQL database."""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from scripts.seed_matching_demo import SOURCE_ID, seed_synthetic
from services.common.db import make_engine, session_scope
from services.common.models import (
    LoanProduct,
    Match,
    NotificationLog,
    NotificationMatch,
    OutboxEvent,
    UploadBatch,
    User,
    WorkflowExecution,
)
from services.eligibility.transport import signature, verify
from services.notifications.content import DISCLAIMER, recipient_for, render, transport_mode
from services.notifications.storage import (
    accept_event,
    compose,
    mock_send,
    next_reservation,
    record_result,
)


@pytest.fixture(scope="module")
def engine():
    name = os.environ["TEST_DB_NAME"].removesuffix("_test") + "_notification_test"
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
def setup_data(engine, monkeypatch):
    monkeypatch.setenv("NOTIFICATION_MODE", "test")
    monkeypatch.setenv("NOTIFICATION_TRANSPORT", "mock")
    monkeypatch.setenv("NOTIFICATION_SES_ENABLED", "0")
    monkeypatch.setenv("NOTIFICATION_TEST_EMAIL", "owner+base@gmail.com")
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE notification_matches, notification_logs, matches, workflow_executions, outbox_events, upload_row_errors, users, upload_batches, loan_products, product_sources CASCADE"))
    seed_synthetic(engine)
    batch_id = uuid.uuid4()
    event_id = uuid.uuid5(uuid.NAMESPACE_URL, f"matching.completed.v1:{batch_id}")
    users = [uuid.uuid4() for _ in range(3)]
    with session_scope(engine) as session:
        session.add(UploadBatch(id=batch_id, object_bucket="test", object_key=f"uploads/{batch_id}/test.csv",
                                schema_version=1, status="matched", accepted_rows=3, total_rows=3, is_demo=True))
        session.flush()
        for index, user_id in enumerate(users):
            session.add(User(id=user_id, upload_batch_id=batch_id, source_user_id=f"demo-{index}",
                             email=f"csv-{index}@example.invalid", monthly_income=Decimal(50000),
                             credit_score=710, age=30, employment_status="salaried"))
        parent = WorkflowExecution(id=uuid.uuid4(), workflow_type="matching", upload_batch_id=batch_id,
                                   status="succeeded", metrics={})
        session.add(parent)
        session.flush()
        products = session.scalars(select(LoanProduct).where(LoanProduct.source_id == SOURCE_ID,
                                                              LoanProduct.is_current.is_(True))).all()
        assert len(products) == 2
        for user_id, product_list in ((users[0], products[:1]), (users[1], products)):
            for product in product_list:
                session.add(Match(user_id=user_id, product_id=product.id, workflow_execution_id=parent.id,
                                  status="potential", evaluation_method="deterministic",
                                  qualification_reasons=[{"code": "demo"}], decision_input_sha256="a" * 64))
        session.add(OutboxEvent(event_id=event_id, event_type="matching.completed.v1", aggregate_id=batch_id,
                                payload={"batch_id": str(batch_id), "matching_run_id": str(parent.id)}))
    return engine, batch_id, event_id, users


def _start(data):
    engine, batch_id, event_id, _ = data
    accepted = accept_event(engine, event_id=event_id, batch_id=batch_id)
    assert accepted["accepted"]
    return uuid.UUID(accepted["run_id"])


def test_grouping_and_mock_idempotency(setup_data):
    engine, batch_id, event_id, users = setup_data
    run_id = _start(setup_data)
    counts = []
    while True:
        next_item = next_reservation(engine, run_id)
        if next_item["done"]:
            break
        if next_item.get("skip"):
            continue
        counts.append(next_item["match_count"])
        notification_id = uuid.UUID(next_item["notification_id"])
        preview = compose(engine, notification_id, begin_send=False)
        assert DISCLAIMER in preview["text"] and DISCLAIMER in preview["html"]
        assert "csv-" not in preview["text"] and "credit score" not in preview["text"].lower()
        prepared = compose(engine, notification_id, begin_send=True)
        assert prepared["recipient"] == recipient_for(uuid.UUID(next_item["user_id"]))
        response = mock_send(engine, notification_id, prepared["recipient"])
        assert record_result(engine, notification_id, message_id=response["message_id"])["state"] == "mocked"
    assert sorted(counts) == [1, 2]
    with session_scope(engine) as session:
        logs = session.scalars(select(NotificationLog)).all()
        assert len(logs) == 2 and all(log.status == "mocked" and log.attempt_count == 1 for log in logs)
        assert session.scalar(select(func.count()).select_from(NotificationMatch)) == 3
        assert all(log.ses_message_id is None for log in logs)
        assert session.get(WorkflowExecution, run_id).status == "succeeded"
    assert accept_event(engine, event_id=event_id, batch_id=batch_id)["accepted"] is False
    assert all("csv-" not in log.recipient_alias for log in logs)
    assert users[2] not in {log.user_id for log in logs}


def test_concurrent_reservation_and_csv_address_rejected(setup_data):
    engine, _, _, users = setup_data
    run_id = _start(setup_data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: next_reservation(engine, run_id), range(2)))
    assert results[0]["notification_id"] == results[1]["notification_id"]
    notification_id = uuid.UUID(results[0]["notification_id"])
    prepared = compose(engine, notification_id, begin_send=True)
    with pytest.raises(ValueError, match="mock_recipient_policy_violation"):
        mock_send(engine, notification_id, "csv-0@example.invalid")
    assert "loan-" in prepared["recipient"]
    assert prepared["recipient"] not in {f"csv-{i}@example.invalid" for i in range(3)}
    assert prepared["recipient"] == recipient_for(users[0]) or prepared["recipient"] == recipient_for(users[1])


def test_interrupted_send_becomes_ambiguous_and_not_resent(setup_data):
    engine, _, _, _ = setup_data
    run_id = _start(setup_data)
    item = next_reservation(engine, run_id)
    notification_id = uuid.UUID(item["notification_id"])
    compose(engine, notification_id, begin_send=True)
    recovered = next_reservation(engine, run_id)
    assert recovered["state"] == "ambiguous" and recovered["skip"]
    with session_scope(engine) as session:
        log = session.get(NotificationLog, notification_id)
        assert log.status == "ambiguous" and log.attempt_count == 1
    with pytest.raises(ValueError, match="notification_not_reserved"):
        compose(engine, notification_id, begin_send=True)


def test_ses_acceptance_and_uncertain_failure_are_distinct(setup_data, monkeypatch):
    engine, _, _, _ = setup_data
    monkeypatch.setenv("NOTIFICATION_TRANSPORT", "ses")
    monkeypatch.setenv("NOTIFICATION_SES_ENABLED", "1")
    monkeypatch.setenv("NOTIFICATION_TEST_EMAIL", "owner@gmail.com")
    monkeypatch.setenv("NOTIFICATION_FROM_EMAIL", "sender@verified.test")
    run_id = _start(setup_data)
    item = next_reservation(engine, run_id)
    notification_id = uuid.UUID(item["notification_id"])
    compose(engine, notification_id, begin_send=True)
    assert record_result(engine, notification_id, message_id="ses-test-message-id")["state"] == "sent"
    with session_scope(engine) as session:
        log = session.get(NotificationLog, notification_id)
        assert log.ses_message_id == "ses-test-message-id" and log.sent_at is not None
    item = next_reservation(engine, run_id)
    notification_id = uuid.UUID(item["notification_id"])
    compose(engine, notification_id, begin_send=True)
    assert record_result(engine, notification_id, message_id=None,
                         error_code="ses_node_error_or_timeout")["state"] == "ambiguous"
    with session_scope(engine) as session:
        log = session.get(NotificationLog, notification_id)
        assert log.ses_message_id is None and log.last_error_code == "ses_node_error_or_timeout"


def test_test_recipient_and_html_escaping(monkeypatch):
    monkeypatch.setenv("NOTIFICATION_MODE", "production")
    with pytest.raises(ValueError, match="disabled"):
        recipient_for(uuid.uuid4())
    monkeypatch.setenv("NOTIFICATION_MODE", "test")
    monkeypatch.setenv("NOTIFICATION_TEST_EMAIL", "owner+first@gmail.com")
    assert recipient_for(uuid.UUID("11111111-1111-1111-1111-111111111111")) == "owner+loan-11111111@gmail.com"
    product = {"institution": "<Bank>", "name": "A & B", "source_url": "https://example.invalid/?x=\"bad\"",
               "source_type": "synthetic", "rate": None}
    content = render([product], synthetic=True)
    assert "&lt;Bank&gt;" in content["html"] and "&quot;bad&quot;" in content["html"]
    assert "<Bank>" not in content["html"] and "<Bank>" in content["text"]
    assert "SYNTHETIC DEMONSTRATION" in content["text"]


def test_ses_default_disabled_and_workflow_contract(monkeypatch):
    monkeypatch.setenv("NOTIFICATION_TRANSPORT", "ses")
    monkeypatch.setenv("NOTIFICATION_SES_ENABLED", "0")
    with pytest.raises(ValueError, match="not_explicitly_enabled"):
        transport_mode()
    raw = (Path(__file__).resolve().parents[2] / "workflows/notifications.json").read_text()
    workflow = json.loads(raw)
    names = {node["name"] for node in workflow["nodes"]}
    assert {"Signed Notification Webhook", "Authenticate and Durably Accept Event",
            "Fetch and Reserve Next User Group", "Enforce Test Recipient and Begin Attempt",
            "AWS SES Send to Controlled Test Inbox", "Record SES Acceptance or Ambiguity"} <= names
    assert any(node["type"] == "n8n-nodes-base.awsSes" for node in workflow["nodes"])
    assert "MATCHING_WEBHOOK_SECRET" not in raw and "AWS_SECRET_ACCESS_KEY" not in raw


def test_zero_matches_produce_no_notification(setup_data):
    engine, batch_id, event_id, _ = setup_data
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM matches"))
    run_id = _start(setup_data)
    assert next_reservation(engine, run_id)["done"]
    with session_scope(engine) as session:
        assert session.scalar(select(func.count()).select_from(NotificationLog)) == 0
    assert accept_event(engine, event_id=event_id, batch_id=batch_id)["accepted"] is False


def test_unverified_product_versions_are_excluded(setup_data):
    engine, _, _, _ = setup_data
    with session_scope(engine) as session:
        for product in session.scalars(select(LoanProduct).where(LoanProduct.source_id == SOURCE_ID)):
            product.verification_status = "review_required"
    run_id = _start(setup_data)
    while not next_reservation(engine, run_id)["done"]:
        pass
    with session_scope(engine) as session:
        assert session.scalar(select(func.count()).select_from(NotificationLog)) == 0


def test_signed_completion_requires_expected_event_type(monkeypatch):
    import time

    monkeypatch.setenv("MATCHING_WEBHOOK_SECRET", "n" * 40)
    body = {"event_id": str(uuid.uuid4()), "event_type": "matching.completed.v1",
            "batch_id": str(uuid.uuid4())}
    timestamp = str(int(time.time()))
    headers = {"X-Loan-Event-Id": body["event_id"], "X-Loan-Timestamp": timestamp,
               "X-Loan-Signature": signature(body, timestamp, "n" * 40)}
    assert verify(body, headers, expected_type="matching.completed.v1").event_type == "matching.completed.v1"
    with pytest.raises(ValueError, match="unexpected_event_type"):
        verify(body, headers)
