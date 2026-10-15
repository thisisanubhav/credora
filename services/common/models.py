"""Versioned PostgreSQL persistence contract; Alembic owns schema changes."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UploadBatch(Base):
    __tablename__ = "upload_batches"
    __table_args__ = (
        UniqueConstraint("object_bucket", "object_key", name="uq_upload_batches_object"),
        CheckConstraint("schema_version > 0", name="ck_upload_batches_schema_version"),
        CheckConstraint(
            "status IN ('uploaded','processing','processed','processed_with_errors',"
            "'rejected','failed','matching','matched','match_failed')",
            name="ck_upload_batches_status",
        ),
        CheckConstraint(
            "total_rows >= 0 AND accepted_rows >= 0 AND rejected_rows >= 0 "
            "AND accepted_rows + rejected_rows <= total_rows",
            name="ck_upload_batches_counts",
        ),
        CheckConstraint("char_length(object_bucket) BETWEEN 1 AND 255", name="ck_upload_batches_bucket"),
        CheckConstraint("char_length(object_key) BETWEEN 1 AND 1024", name="ck_upload_batches_key"),
        CheckConstraint("idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'", name="ck_upload_batches_idempotency_hash"),
        CheckConstraint("request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_upload_batches_fingerprint"),
        Index("ix_upload_batches_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_bucket: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    object_version_id: Mapped[str | None] = mapped_column(Text)
    object_etag: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    processing_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    processing_lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'uploaded'"))
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    accepted_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    processing_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    users: Mapped[list[User]] = relationship(back_populates="upload_batch")
    row_errors: Mapped[list[UploadRowError]] = relationship(back_populates="upload_batch")


class UploadRowError(Base):
    __tablename__ = "upload_row_errors"
    __table_args__ = (
        UniqueConstraint("upload_batch_id", "row_number", name="uq_upload_row_errors_batch_row"),
        CheckConstraint("row_number > 1", name="ck_upload_row_errors_row_number"),
        CheckConstraint("jsonb_typeof(codes) = 'array' AND jsonb_array_length(codes) > 0", name="ck_upload_row_errors_codes"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("upload_batches.id", ondelete="RESTRICT"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    upload_batch: Mapped[UploadBatch] = relationship(back_populates="row_errors")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("upload_batch_id", "source_user_id", name="uq_users_batch_source_id"),
        CheckConstraint("char_length(source_user_id) BETWEEN 1 AND 128", name="ck_users_source_id"),
        CheckConstraint("char_length(email) BETWEEN 3 AND 320 AND email = lower(email)", name="ck_users_email_normalized"),
        CheckConstraint("monthly_income >= 0", name="ck_users_income"),
        CheckConstraint("income_currency ~ '^[A-Z]{3}$'", name="ck_users_currency"),
        CheckConstraint("credit_score BETWEEN 0 AND 1000", name="ck_users_credit_score"),
        CheckConstraint("age BETWEEN 0 AND 130", name="ck_users_age"),
        CheckConstraint("employment_status_raw IS NULL OR char_length(employment_status_raw) BETWEEN 1 AND 128", name="ck_users_employment_raw"),
        CheckConstraint(
            "employment_status IN ('salaried','self_employed','contract','unemployed',"
            "'retired','student','other')",
            name="ck_users_employment_status",
        ),
        Index("ix_users_batch", "upload_batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("upload_batches.id", ondelete="RESTRICT"), nullable=False)
    source_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    monthly_income: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    income_currency: Mapped[str | None] = mapped_column(String(3))
    credit_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    employment_status: Mapped[str] = mapped_column(Text, nullable=False)
    employment_status_raw: Mapped[str | None] = mapped_column(Text)
    age: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    upload_batch: Mapped[UploadBatch] = relationship(back_populates="users")
    matches: Mapped[list[Match]] = relationship(back_populates="user")


class ProductSource(Base):
    __tablename__ = "product_sources"
    __table_args__ = (
        UniqueConstraint("base_url", name="uq_product_sources_base_url"),
        CheckConstraint("crawl_interval_hours > 0", name="ck_product_sources_interval"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 255", name="ck_product_sources_name"),
        CheckConstraint("base_url LIKE 'https://%' AND discovery_url LIKE 'https://%'", name="ck_product_sources_https"),
        CheckConstraint("source_type IN ('official','synthetic')", name="ck_product_sources_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'official'"))
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    discovery_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    crawl_interval_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    terms_reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    robots_reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_attempted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_succeeded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    products: Mapped[list[LoanProduct]] = relationship(back_populates="source")


class LoanProduct(Base):
    __tablename__ = "loan_products"
    __table_args__ = (
        UniqueConstraint("source_id", "source_product_key", "version", name="uq_loan_products_version"),
        CheckConstraint("version > 0", name="ck_loan_products_version"),
        CheckConstraint("char_length(source_product_key) BETWEEN 1 AND 1024", name="ck_loan_products_key"),
        CheckConstraint("char_length(product_name) BETWEEN 1 AND 255", name="ck_loan_products_name"),
        CheckConstraint("source_url LIKE 'https://%'", name="ck_loan_products_source_https"),
        CheckConstraint("interest_rate_min_pct IS NULL OR interest_rate_min_pct >= 0", name="ck_loan_products_rate_min"),
        CheckConstraint("interest_rate_max_pct IS NULL OR interest_rate_max_pct >= interest_rate_min_pct OR interest_rate_min_pct IS NULL", name="ck_loan_products_rate_order"),
        CheckConstraint("interest_rate_max_pct IS NULL OR interest_rate_max_pct >= 0", name="ck_loan_products_rate_max"),
        CheckConstraint("min_monthly_income IS NULL OR min_monthly_income >= 0", name="ck_loan_products_income"),
        CheckConstraint("min_credit_score IS NULL OR min_credit_score BETWEEN 0 AND 1000", name="ck_loan_products_score_min"),
        CheckConstraint("max_credit_score IS NULL OR max_credit_score BETWEEN 0 AND 1000", name="ck_loan_products_score_max"),
        CheckConstraint("min_credit_score IS NULL OR max_credit_score IS NULL OR min_credit_score <= max_credit_score", name="ck_loan_products_score_order"),
        CheckConstraint("min_age IS NULL OR min_age BETWEEN 0 AND 130", name="ck_loan_products_age_min"),
        CheckConstraint("max_age IS NULL OR max_age BETWEEN 0 AND 130", name="ck_loan_products_age_max"),
        CheckConstraint("min_age IS NULL OR max_age IS NULL OR min_age <= max_age", name="ck_loan_products_age_order"),
        CheckConstraint("eligible_employment_statuses IS NULL OR cardinality(eligible_employment_statuses) > 0", name="ck_loan_products_employment_nonempty"),
        CheckConstraint("jsonb_typeof(eligibility_rules) = 'object'", name="ck_loan_products_rules_object"),
        CheckConstraint("rule_schema_version > 0", name="ck_loan_products_rule_schema"),
        CheckConstraint("extraction_method IN ('deterministic','gemini','mixed')", name="ck_loan_products_extraction_method"),
        CheckConstraint("verification_status IN ('verified','review_required','invalid','stale')", name="ck_loan_products_verification_status"),
        CheckConstraint(
            "verification_status <> 'verified' OR COALESCE(("
            "eligibility_rules->>'completeness' = 'complete' "
            "AND jsonb_typeof(eligibility_rules->'all') = 'array' "
            "AND jsonb_typeof(eligibility_rules->'any') = 'array' "
            "AND jsonb_typeof(eligibility_rules->'ambiguous') = 'array' "
            "AND (jsonb_array_length(eligibility_rules->'all') + "
            "jsonb_array_length(eligibility_rules->'any') + "
            "jsonb_array_length(eligibility_rules->'ambiguous')) > 0), false)",
            name="ck_loan_products_verified_rules",
        ),
        CheckConstraint("extraction_method = 'deterministic' OR (model_name IS NOT NULL AND prompt_version IS NOT NULL)", name="ck_loan_products_model_provenance"),
        CheckConstraint("source_content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_loan_products_content_hash"),
        CheckConstraint("currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'", name="ck_loan_products_currency"),
        CheckConstraint("jsonb_typeof(criterion_states) = 'object'", name="ck_loan_products_criterion_states"),
        Index("uq_loan_products_current", "source_id", "source_product_key", unique=True, postgresql_where=text("is_current")),
        Index("ix_loan_products_matchable", "source_id", postgresql_where=text("is_current AND verification_status = 'verified' AND retired_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_sources.id", ondelete="RESTRICT"), nullable=False)
    source_product_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    criterion_states: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    interest_rate_min_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    interest_rate_max_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    interest_rate_text: Mapped[str | None] = mapped_column(Text)
    min_monthly_income: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    min_credit_score: Mapped[int | None] = mapped_column(SmallInteger)
    max_credit_score: Mapped[int | None] = mapped_column(SmallInteger)
    min_age: Mapped[int | None] = mapped_column(SmallInteger)
    max_age: Mapped[int | None] = mapped_column(SmallInteger)
    eligible_employment_statuses: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    eligibility_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rule_schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    raw_eligibility_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    retrieved_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    source: Mapped[ProductSource] = relationship(back_populates="products")
    matches: Mapped[list[Match]] = relationship(back_populates="product")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "event_type", name="uq_outbox_events_aggregate_type"),
        CheckConstraint("event_type IN ('upload_batch.ready.v1','matching.completed.v1')", name="ck_outbox_events_type"),
        CheckConstraint("status IN ('pending','processing','delivered','failed_permanent')", name="ck_outbox_events_status"),
        CheckConstraint("retry_count >= 0", name="ck_outbox_events_retry_count"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_outbox_events_payload_object"),
        Index("ix_outbox_events_due", "next_attempt_at", postgresql_where=text("status = 'pending'")),
        Index("ix_outbox_events_expired_claim", "claim_expires_at", postgresql_where=text("status = 'processing'")),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("upload_batches.id", ondelete="RESTRICT"), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_workflow_executions_event_id"),
        UniqueConstraint("n8n_execution_id", name="uq_workflow_executions_n8n_id"),
        CheckConstraint("workflow_type IN ('discovery','matching','notification','outbox_reconcile')", name="ck_workflow_executions_type"),
        CheckConstraint("status IN ('running','succeeded','failed','partial')", name="ck_workflow_executions_status"),
        CheckConstraint("workflow_type NOT IN ('matching','notification') OR upload_batch_id IS NOT NULL", name="ck_workflow_executions_batch_scope"),
        CheckConstraint("jsonb_typeof(metrics) = 'object'", name="ck_workflow_executions_metrics_object"),
        Index("ix_workflow_executions_type_status_started", "workflow_type", "status", "started_at"),
        Index("ix_workflow_executions_batch", "upload_batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    n8n_execution_id: Mapped[str | None] = mapped_column(Text)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("outbox_events.event_id", ondelete="RESTRICT"))
    parent_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="RESTRICT"))
    workflow_type: Mapped[str] = mapped_column(Text, nullable=False)
    upload_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("upload_batches.id", ondelete="RESTRICT"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_sources.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_matches_user_product_version"),
        CheckConstraint("status IN ('potential','withdrawn')", name="ck_matches_status"),
        CheckConstraint("evaluation_method IN ('deterministic','deterministic_plus_llm')", name="ck_matches_evaluation_method"),
        CheckConstraint("jsonb_typeof(qualification_reasons) = 'array'", name="ck_matches_reasons_array"),
        CheckConstraint("decision_input_sha256 ~ '^[0-9a-f]{64}$'", name="ck_matches_decision_hash"),
        Index("ix_matches_user_notified", "user_id", "notified_at"),
        Index("ix_matches_unnotified", "user_id", postgresql_where=text("notified_at IS NULL AND status = 'potential'")),
        Index("ix_matches_product", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loan_products.id", ondelete="RESTRICT"), nullable=False)
    workflow_execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'potential'"))
    evaluation_method: Mapped[str] = mapped_column(Text, nullable=False)
    qualification_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    decision_input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    matched_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    notified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    user: Mapped[User] = relationship(back_populates="matches")
    product: Mapped[LoanProduct] = relationship(back_populates="matches")


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notification_logs_idempotency"),
        UniqueConstraint("ses_message_id", name="uq_notification_logs_ses_message_id"),
        CheckConstraint("status IN ('reserved','sending','sent','failed','ambiguous','mocked')", name="ck_notification_logs_status"),
        CheckConstraint("delivery_mode IN ('mock','ses')", name="ck_notification_logs_delivery_mode"),
        CheckConstraint("attempt_count >= 0", name="ck_notification_logs_attempts"),
        CheckConstraint("char_length(recipient_alias) BETWEEN 3 AND 320 AND recipient_alias = lower(recipient_alias)", name="ck_notification_logs_alias"),
        Index("ix_notification_logs_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_alias: Mapped[str] = mapped_column(Text, nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'mock'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'reserved'"))
    ses_message_id: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    reserved_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    match_links: Mapped[list[NotificationMatch]] = relationship(back_populates="notification")


class NotificationMatch(Base):
    """Normalized membership makes each matched product notify at most once."""

    __tablename__ = "notification_matches"
    __table_args__ = (
        UniqueConstraint("match_id", name="uq_notification_matches_match"),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("notification_logs.id", ondelete="RESTRICT"), primary_key=True)
    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("matches.id", ondelete="RESTRICT"), primary_key=True)

    notification: Mapped[NotificationLog] = relationship(back_populates="match_links")
