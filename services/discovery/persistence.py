"""Short PostgreSQL transactions for source tracking and immutable product versions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from services.common.db import session_scope
from services.common.models import LoanProduct, ProductSource, WorkflowExecution
from services.discovery.extraction import ProductCandidate
from services.discovery.sources import SOURCES, require_source


def _source_row(session: Any, key: str) -> ProductSource:
    definition = require_source(key)
    session.execute(insert(ProductSource).values(
        id=uuid.uuid4(), name=definition.institution, base_url=definition.origin,
        discovery_url=definition.url, crawl_interval_hours=24,
    ).on_conflict_do_nothing(index_elements=["base_url"]))
    return session.scalar(select(ProductSource).where(
        ProductSource.base_url == definition.origin,
    ).with_for_update())


def start_run(engine: Engine) -> uuid.UUID:
    with session_scope(engine) as session:
        for key in SOURCES:
            _source_row(session, key)
        run = WorkflowExecution(
            workflow_type="discovery", status="running",
            metrics={"expected_sources": len(SOURCES), "sources": {}},
        )
        session.add(run)
        session.flush()
        return run.id


def mark_attempt(engine: Engine, key: str) -> None:
    with session_scope(engine) as session:
        source = _source_row(session, key)
        source.last_attempted_at = datetime.now(UTC)


def _meaningful(data: ProductCandidate | LoanProduct) -> dict[str, Any]:
    if isinstance(data, ProductCandidate):
        return {
            "product_name": data.product_name, "source_url": data.source_url,
            "interest_rate_min_pct": data.interest_rate_min_pct,
            "interest_rate_max_pct": data.interest_rate_max_pct,
            "interest_rate_text": data.interest_rate_text,
            "currency_code": data.currency_code,
            "min_monthly_income": data.min_monthly_income,
            "min_credit_score": data.min_credit_score,
            "max_credit_score": data.max_credit_score,
            "min_age": data.min_age, "max_age": data.max_age,
            "eligible_employment_statuses": data.eligible_employment_statuses,
            "criterion_states": data.criterion_states,
            "eligibility_rules": data.eligibility_rules.model_dump(mode="json"),
            "raw_eligibility_text": data.raw_eligibility_text,
            "source_content_sha256": data.source_content_sha256,
            "extraction_method": data.extraction_method,
            "model_name": data.model_name,
            "prompt_version": data.prompt_version,
            "verification_status": data.verification_status,
        }
    return {name: getattr(data, name) for name in (
        "product_name", "source_url", "interest_rate_min_pct", "interest_rate_max_pct",
        "interest_rate_text", "currency_code", "min_monthly_income", "min_credit_score",
        "max_credit_score", "min_age", "max_age", "eligible_employment_statuses",
        "criterion_states", "eligibility_rules", "raw_eligibility_text", "source_content_sha256",
        "extraction_method", "model_name", "prompt_version", "verification_status",
    )}


def persist_product(engine: Engine, candidate: ProductCandidate) -> tuple[str, uuid.UUID, int]:
    definition = require_source(candidate.source_key)
    if candidate.source_url != definition.url or candidate.product_name != definition.product_name:
        raise ValueError("product_source_mismatch")
    with session_scope(engine) as session:
        source = _source_row(session, candidate.source_key)
        current = session.scalar(select(LoanProduct).where(
            LoanProduct.source_id == source.id,
            LoanProduct.source_product_key == "personal-loan",
            LoanProduct.is_current.is_(True),
        ).with_for_update())
        now = datetime.now(UTC)
        if current and _meaningful(current) == _meaningful(candidate):
            current.last_seen_at = now
            source.last_succeeded_at = now
            return "unchanged", current.id, current.version
        if current and current.verification_status == "verified" and candidate.verification_status != "verified":
            return "preserved_verified", current.id, current.version
        version = 1 if current is None else current.version + 1
        if current:
            current.is_current = False
            session.flush()
        item = LoanProduct(
            id=uuid.uuid4(), source_id=source.id, source_product_key="personal-loan",
            version=version, is_current=True, rule_schema_version=1,
            retrieved_at=candidate.retrieved_at, last_seen_at=now,
            **_meaningful(candidate),
        )
        session.add(item)
        source.last_succeeded_at = now
        session.flush()
        return "created" if version == 1 else "versioned", item.id, version


def record_source(engine: Engine, run_id: uuid.UUID, key: str, outcome: str) -> dict[str, Any]:
    require_source(key)
    if outcome not in {"created", "versioned", "unchanged", "preserved_verified", "failed"}:
        raise ValueError("invalid_discovery_outcome")
    with session_scope(engine) as session:
        run = session.scalar(select(WorkflowExecution).where(
            WorkflowExecution.id == run_id, WorkflowExecution.workflow_type == "discovery",
        ).with_for_update())
        if run is None:
            raise ValueError("unknown_discovery_run")
        metrics = dict(run.metrics)
        results = dict(metrics.get("sources", {}))
        results[key] = outcome
        metrics["sources"] = results
        run.metrics = metrics
        if len(results) == len(SOURCES):
            successes = sum(value in {"created", "versioned", "unchanged"} for value in results.values())
            run.status = "succeeded" if successes == len(SOURCES) else ("partial" if successes else "failed")
            run.finished_at = datetime.now(UTC)
        return {"run_id": str(run_id), "source_key": key, "outcome": outcome,
                "run_status": run.status, "completed_sources": len(results)}
