"""Add one extra clearly synthetic, higher-score fixture for notification grouping."""

from __future__ import annotations

import copy
import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine

from scripts.seed_matching_demo import ORIGIN, SOURCE_ID, seed_synthetic
from services.common.db import make_engine, session_scope
from services.common.models import LoanProduct


def seed_notification_demo(engine: Engine) -> None:
    seed_synthetic(engine)
    with session_scope(engine) as session:
        key = "demo-profile-higher-score"
        if session.scalar(select(LoanProduct.id).where(LoanProduct.source_id == SOURCE_ID,
                                                         LoanProduct.source_product_key == key)) is not None:
            return
        original = session.scalar(select(LoanProduct).where(LoanProduct.source_id == SOURCE_ID,
                                                              LoanProduct.source_product_key == "demo-profile",
                                                              LoanProduct.is_current.is_(True)))
        if original is None:
            raise ValueError("base_synthetic_fixture_missing")
        rules = copy.deepcopy(original.eligibility_rules)
        score_rules = [rule for rule in rules["all"] if rule["field"] == "credit_score"]
        if len(score_rules) != 1:
            raise ValueError("base_synthetic_score_rule_changed")
        score_rules[0]["value"] = "750"
        score_rules[0]["evidence"]["quote"] = "SYNTHETIC: credit score at least 750 points"
        raw = "SYNTHETIC DEMONSTRATION ONLY: age at least 25; score at least 750; salaried"
        now = datetime.now(UTC)
        session.add(LoanProduct(id=uuid.uuid5(uuid.NAMESPACE_URL, f"{ORIGIN}/{key}/v1"),
            source_id=SOURCE_ID, source_product_key=key, version=1, is_current=True,
            product_name="SYNTHETIC DEMO — higher-score profile", source_url=ORIGIN + "/fixture",
            currency_code=None, criterion_states=original.criterion_states,
            interest_rate_min_pct=None, interest_rate_max_pct=None, interest_rate_text=None,
            min_monthly_income=None, min_credit_score=750, max_credit_score=None,
            min_age=25, max_age=None, eligible_employment_statuses=["salaried"],
            eligibility_rules=rules, rule_schema_version=1, raw_eligibility_text=raw,
            source_content_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            extraction_method="deterministic", verification_status="verified",
            retrieved_at=now, last_seen_at=now))


if __name__ == "__main__":
    engine = make_engine()
    try:
        seed_notification_demo(engine)
        print("Additional higher-score synthetic demo product ready; official lenders untouched.")
    finally:
        engine.dispose()
