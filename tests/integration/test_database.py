"""Real PostgreSQL integrity tests; the guarded *_test database is disposable."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from services.common.db import make_engine, session_scope
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


@pytest.fixture(scope="module")
def engine():
    name = os.environ["TEST_DB_NAME"]
    assert name.endswith("_test")
    assert name not in {os.environ["POSTGRES_DB"], os.environ["N8N_DB_NAME"]}
    database_engine = make_engine(role="migration", database=name)
    old_name = os.environ.get("DATABASE_NAME")
    os.environ["DATABASE_NAME"] = name
    config = Config("database/alembic.ini")
    try:
        # Downgrade is destructive ONLY in the dedicated, guarded test database.
        # M3's NULL-currency users cannot be represented by M2's NOT NULL schema.
        # This disposable database is rebuilt below; remove those test rows first.
        if "users" in inspect(database_engine).get_table_names():
            with database_engine.begin() as connection:
                connection.execute(text("TRUNCATE TABLE users CASCADE"))
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        assert set(inspect(database_engine).get_table_names()) == {
            "alembic_version", "upload_batches", "users", "product_sources", "loan_products",
            "matches", "workflow_executions", "outbox_events", "notification_logs", "notification_matches", "upload_row_errors",
        }
        command.downgrade(config, "base")
        assert set(inspect(database_engine).get_table_names()) <= {"alembic_version"}
        command.upgrade(config, "head")
        yield database_engine
    finally:
        if old_name is None:
            os.environ.pop("DATABASE_NAME", None)
        else:
            os.environ["DATABASE_NAME"] = old_name
        database_engine.dispose()


def batch(session, *, source_id: str | None = None) -> UploadBatch:
    batch_id = uuid.uuid4()
    item = UploadBatch(
        id=batch_id,
        object_bucket="test-bucket",
        object_key=f"uploads/{batch_id}/users.csv",
        schema_version=1,
    )
    session.add(item)
    session.flush()
    return item


def user(session, upload: UploadBatch, *, source_id: str = "one", income: Decimal = Decimal("1234.56")) -> User:
    item = User(
        upload_batch_id=upload.id,
        source_user_id=source_id,
        email="test@example.invalid",
        monthly_income=income,
        income_currency="USD",
        credit_score=700,
        employment_status="salaried",
        age=30,
    )
    session.add(item)
    session.flush()
    return item


def product(session, *, source: ProductSource | None = None, version: int = 1, current: bool = True) -> LoanProduct:
    if source is None:
        source = ProductSource(
            name="Fixture lender", base_url=f"https://{uuid.uuid4()}.invalid",
            discovery_url="https://fixture.invalid/loans", crawl_interval_hours=24,
        )
        session.add(source)
        session.flush()
    now = datetime.now(UTC)
    item = LoanProduct(
        source_id=source.id,
        source_product_key="fixture-loan",
        version=version,
        is_current=current,
        product_name="Synthetic fixture loan",
        source_url="https://fixture.invalid/loans/one",
        interest_rate_min_pct=Decimal("12.3456"),
        min_monthly_income=Decimal("1000.00"),
        eligibility_rules={"schema_version": 1, "all": [], "any": [], "ambiguous": []},
        rule_schema_version=1,
        raw_eligibility_text="Synthetic test fixture; not a real offer",
        source_content_sha256="a" * 64,
        extraction_method="deterministic",
        verification_status="review_required",
        retrieved_at=now,
        last_seen_at=now,
    )
    session.add(item)
    session.flush()
    return item


def execution(session, upload: UploadBatch, *, kind: str = "matching") -> WorkflowExecution:
    item = WorkflowExecution(workflow_type=kind, upload_batch_id=upload.id, status="running")
    session.add(item)
    session.flush()
    return item


def match(session, person: User, loan: LoanProduct, run: WorkflowExecution) -> Match:
    item = Match(
        user_id=person.id,
        product_id=loan.id,
        workflow_execution_id=run.id,
        evaluation_method="deterministic",
        qualification_reasons=[{"code": "fixture_only"}],
        decision_input_sha256="b" * 64,
    )
    session.add(item)
    session.flush()
    return item


def test_migration_constraints_and_indexes(engine):
    inspector = inspect(engine)
    assert "uq_users_batch_source_id" in {c["name"] for c in inspector.get_unique_constraints("users")}
    assert "ck_users_income" in {c["name"] for c in inspector.get_check_constraints("users")}
    assert "uq_loan_products_current" in {i["name"] for i in inspector.get_indexes("loan_products")}
    assert "ix_outbox_events_due" in {i["name"] for i in inspector.get_indexes("outbox_events")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "8a9d6c2e15b0"


def test_users_precision_and_cross_batch_identity(engine):
    with session_scope(engine) as session:
        first, second = batch(session), batch(session)
        one = user(session, first, income=Decimal("999999999999.99"))
        two = user(session, second)
        first_id, second_id = one.id, two.id
    with session_scope(engine) as session:
        assert session.get(User, first_id).monthly_income == Decimal("999999999999.99")
        assert session.get(User, second_id).source_user_id == "one"


@pytest.mark.parametrize("change", [
    {"monthly_income": Decimal("-1.00")}, {"credit_score": 1001}, {"age": 131},
    {"employment_status": "guess"}, {"income_currency": "usd"}, {"email": "UPPER@EXAMPLE.INVALID"},
])
def test_invalid_user_rejected(engine, change):
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        item = user(session, batch(session))
        for field, value in change.items():
            setattr(item, field, value)
        session.flush()


def test_duplicate_user_within_batch_and_fk(engine):
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        upload = batch(session)
        user(session, upload)
        user(session, upload)
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        user(session, UploadBatch(id=uuid.uuid4()))


def test_product_versions_and_current_uniqueness(engine):
    with session_scope(engine) as session:
        old = product(session, current=False)
        source = old.source
        new = product(session, source=source, version=2)
        old_id, new_id = old.id, new.id
    with session_scope(engine) as session:
        assert session.get(LoanProduct, old_id).version == 1
        assert session.get(LoanProduct, new_id).version == 2
        assert session.get(LoanProduct, old_id).interest_rate_min_pct == Decimal("12.3456")
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        current = session.get(LoanProduct, new_id)
        product(session, source=current.source, version=3)


def test_unverified_or_empty_product_rules_cannot_be_marked_verified(engine):
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        item = product(session)
        item.verification_status = "verified"
        session.flush()
    with session_scope(engine) as session:
        item = product(session)
        item.eligibility_rules = {
            "schema_version": 1, "completeness": "complete",
            "all": [{"field": "age", "operator": "gte", "value": "18", "unit": "years",
                     "evidence": {"quote": "Synthetic fixture, age 18", "source_url": item.source_url}}],
            "any": [], "ambiguous": [],
        }
        item.verification_status = "verified"
        session.flush()
        assert item.verification_status == "verified"


def test_negative_max_rate_rejected(engine):
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        item = product(session)
        item.interest_rate_min_pct = None
        item.interest_rate_max_pct = Decimal("-1.0000")
        session.flush()


def test_match_idempotency_and_foreign_key(engine):
    with session_scope(engine) as session:
        person = user(session, batch(session))
        loan = product(session)
        run = execution(session, person.upload_batch)
        first = match(session, person, loan, run)
        first_id = first.id
        person_id, product_id, run_id = person.id, loan.id, run.id
    with session_scope(engine) as session:
        statement = insert(Match).values(
            id=uuid.uuid4(), user_id=person_id, product_id=product_id,
            workflow_execution_id=run_id, status="potential", evaluation_method="deterministic",
            qualification_reasons=[], decision_input_sha256="b" * 64,
        ).on_conflict_do_nothing(index_elements=["user_id", "product_id"])
        assert session.execute(statement.returning(Match.id)).scalar_one_or_none() is None
        assert session.get(Match, first_id).status == "potential"
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(Match(
            user_id=uuid.uuid4(), product_id=product_id, workflow_execution_id=run_id,
            evaluation_method="deterministic", qualification_reasons=[], decision_input_sha256="b" * 64,
        ))
        session.flush()


def test_outbox_idempotency_and_execution_event_claim(engine):
    with session_scope(engine) as session:
        upload = batch(session)
        event = OutboxEvent(event_type="upload_batch.ready.v1", aggregate_id=upload.id, payload={"batch_id": str(upload.id)})
        session.add(event)
        session.flush()
        run = WorkflowExecution(workflow_type="matching", upload_batch_id=upload.id, status="running", event_id=event.event_id)
        session.add(run)
        session.flush()
        event_id, upload_id = event.event_id, upload.id
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(OutboxEvent(event_type="upload_batch.ready.v1", aggregate_id=upload_id, payload={}))
        session.flush()
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(WorkflowExecution(workflow_type="matching", upload_batch_id=upload_id, status="running", event_id=event_id))
        session.flush()


def test_notification_reservation_and_match_membership(engine):
    with session_scope(engine) as session:
        person = user(session, batch(session))
        loan = product(session)
        run = execution(session, person.upload_batch)
        decision = match(session, person, loan, run)
        notification = NotificationLog(
            workflow_execution_id=run.id, user_id=person.id, idempotency_key="c" * 64,
            recipient_alias="owner+one@example.invalid", template_version="v1",
        )
        session.add(notification)
        session.flush()
        session.add(NotificationMatch(notification_id=notification.id, match_id=decision.id))
        decision_id, notification_id, person_id, run_id = decision.id, notification.id, person.id, run.id
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        session.add(NotificationLog(
            workflow_execution_id=run_id, user_id=person_id, idempotency_key="c" * 64,
            recipient_alias="owner+one@example.invalid", template_version="v1",
        ))
        session.flush()
    with pytest.raises(IntegrityError), session_scope(engine) as session:
        another = NotificationLog(
            workflow_execution_id=run_id, user_id=person_id, idempotency_key="d" * 64,
            recipient_alias="owner+two@example.invalid", template_version="v1",
        )
        session.add(another)
        session.flush()
        session.add(NotificationMatch(notification_id=another.id, match_id=decision_id))
        session.flush()
    with session_scope(engine) as session:
        assert session.get(NotificationLog, notification_id).attempt_count == 0


def test_transaction_rollback_and_session_close(engine):
    upload_id = uuid.uuid4()
    with pytest.raises(RuntimeError), session_scope(engine) as session:
        session.add(UploadBatch(id=upload_id, object_bucket="test", object_key="rollback.csv", schema_version=1))
        session.flush()
        raise RuntimeError("abort")
    with session_scope(engine) as session:
        assert session.get(UploadBatch, upload_id) is None
        captured = session
    assert not captured.in_transaction()


def test_concurrent_outbox_claim_shape(engine):
    with session_scope(engine) as session:
        upload = batch(session)
        session.add(OutboxEvent(event_type="upload_batch.ready.v1", aggregate_id=upload.id, payload={}))
        upload_id = upload.id

    def claim() -> int:
        with session_scope(engine) as session:
            rows = session.execute(
                text("SELECT event_id FROM outbox_events WHERE aggregate_id = :id "
                     "AND status = 'pending' FOR UPDATE SKIP LOCKED"),
                {"id": upload_id},
            ).all()
            for row in rows:
                session.execute(text("UPDATE outbox_events SET status = 'processing', "
                                     "claimed_at = now(), claim_expires_at = now() + interval '30 seconds' "
                                     "WHERE event_id = :id"), {"id": row.event_id})
            return len(rows)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: claim(), range(2)))
    assert sorted(results) == [0, 1]
