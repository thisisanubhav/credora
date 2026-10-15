"""Opt-in synthetic fixtures, never bank facts or publicly crawled products."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import HttpUrl
from sqlalchemy import select

from services.common.db import make_engine, session_scope
from services.common.models import LoanProduct, ProductSource
from services.common.schemas import EligibilityDocument, EmploymentRule, Evidence, NumericRule

ORIGIN = "https://synthetic.invalid"
SOURCE_ID = uuid.uuid5(uuid.NAMESPACE_URL, ORIGIN)


def _rule(field: Literal["age", "credit_score", "monthly_income"], value: str, unit: str, quote: str) -> NumericRule:
    return NumericRule(field=field, operator="gte", value=value, unit=unit,
                       evidence=Evidence(quote=quote, source_url=HttpUrl(ORIGIN + "/fixture")))


def seed_synthetic(engine) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    with session_scope(engine) as session:
        source = session.get(ProductSource, SOURCE_ID)
        if source is None:
            source = ProductSource(id=SOURCE_ID, name="SYNTHETIC TEST FIXTURE — NOT A LENDER",
                source_type="synthetic", base_url=ORIGIN, discovery_url=ORIGIN + "/fixture",
                crawl_interval_hours=24, enabled=False)
            session.add(source)
            session.flush()
        for key, name, income in (
            ("demo-profile", "SYNTHETIC DEMO — profile-only", None),
            ("demo-inr", "SYNTHETIC DEMO — INR income", Decimal(40000)),
        ):
            text = ("SYNTHETIC TEST CONDITIONS ONLY: age at least 25 years; credit score at least 700 points; "
                    "employment status salaried" + ("; monthly income at least INR 40000/month" if income else ""))
            rules: list[NumericRule | EmploymentRule] = [
                _rule("age", "25", "years", "age at least 25 years"),
                _rule("credit_score", "700", "points", "credit score at least 700 points"),
                EmploymentRule(field="employment_status", operator="eq", value="salaried",
                    evidence=Evidence(quote="employment status salaried", source_url=HttpUrl(ORIGIN + "/fixture"))),
            ]
            if income is not None:
                rules.append(_rule("monthly_income", "40000", "INR/month", "monthly income at least INR 40000/month"))
            document = EligibilityDocument(schema_version=1, completeness="complete", all=rules,
                                           any=[], ambiguous=[], unknown_reason=None)
            states = {"minimum_age": "KNOWN", "maximum_age": "NOT_APPLICABLE",
                      "minimum_credit_score": "KNOWN", "maximum_credit_score": "NOT_APPLICABLE",
                      "employment_requirements": "KNOWN", "minimum_monthly_income": "KNOWN" if income else "NOT_APPLICABLE",
                      "currency": "KNOWN" if income else "NOT_APPLICABLE"}
            existing = session.scalar(select(LoanProduct).where(
                LoanProduct.source_id == SOURCE_ID, LoanProduct.source_product_key == key,
                LoanProduct.is_current.is_(True)).with_for_update())
            if existing is not None and existing.criterion_states == states:
                continue
            version = existing.version + 1 if existing is not None else 1
            if existing is not None:
                existing.is_current = False
                session.flush()
            session.add(LoanProduct(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"{ORIGIN}/{key}/v{version}"), source_id=SOURCE_ID,
                source_product_key=key, version=version, is_current=True, product_name=name,
                source_url=ORIGIN + "/fixture", currency_code="INR" if income else None,
                criterion_states=states, interest_rate_min_pct=None, interest_rate_max_pct=None,
                interest_rate_text=None, min_monthly_income=income, min_credit_score=700,
                max_credit_score=None, min_age=25, max_age=None,
                eligible_employment_statuses=["salaried"],
                eligibility_rules=document.model_dump(mode="json"), rule_schema_version=1,
                raw_eligibility_text=text, source_content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                extraction_method="deterministic", verification_status="verified", retrieved_at=now,
                last_seen_at=now,
            ))


if __name__ == "__main__":
    engine = make_engine()
    try:
        seed_synthetic(engine)
        print("Synthetic demo-only products available; official lender records untouched.")
    finally:
        engine.dispose()
