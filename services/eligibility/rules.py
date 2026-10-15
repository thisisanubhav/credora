"""Pure deterministic evaluator; it never decides loan approval."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from services.common.schemas import EligibilityDocument, EmploymentRule, NumericRule

ENGINE_VERSION = "deterministic-v1"
DECISION_CRITERIA = frozenset({
    "minimum_age", "maximum_age", "minimum_credit_score", "maximum_credit_score",
    "minimum_monthly_income", "employment_requirements", "currency",
})
DecisionStatus = Literal["ELIGIBLE_POTENTIAL", "INELIGIBLE", "REVIEW_REQUIRED", "INSUFFICIENT_DATA"]


class UserFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    batch_id: str
    monthly_income: Decimal | None = None
    income_currency: str | None = None
    credit_score: int | None = None
    age: int | None = None
    employment_status: str | None = None


class ProductFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    version: int
    source_type: Literal["official", "synthetic"]
    is_current: bool
    verification_status: str
    retired: bool
    currency_code: str | None = None
    criterion_states: dict[str, str]
    eligibility_rules: EligibilityDocument


class Decision(BaseModel):
    user_id: str
    batch_id: str
    product_id: str
    product_version: int
    status: DecisionStatus
    reasons: list[dict[str, str]]
    evaluated_at: datetime
    engine_version: str = ENGINE_VERSION
    llm_involved: bool = False
    decision_input_sha256: str


def _rule(rule: NumericRule | EmploymentRule, user: UserFacts, product: ProductFacts) -> tuple[str, str]:
    field = rule.field
    value = getattr(user, field)
    if value is None or (field == "employment_status" and value == "other"):
        return "missing", f"{field}_unavailable"
    if isinstance(rule, EmploymentRule):
        expected = [rule.value] if isinstance(rule.value, str) else rule.value
        return ("pass", f"{field}_passed") if value in expected else ("fail", f"{field}_below_requirement")
    if field == "monthly_income":
        currency = rule.unit.removesuffix("/month")
        if user.income_currency is None:
            return "missing", "income_currency_unknown"
        if user.income_currency != currency or product.currency_code != currency:
            return "fail", "income_currency_mismatch"
    actual = Decimal(str(value))
    bounds = rule.value if isinstance(rule.value, tuple) else (rule.value,)
    numbers = [Decimal(bound) for bound in bounds]
    passed = (actual >= numbers[0] if rule.operator == "gte" else
              actual <= numbers[0] if rule.operator == "lte" else
              numbers[0] <= actual <= numbers[1])
    return ("pass", f"{field}_passed") if passed else ("fail", f"{field}_threshold_failed")


def evaluate(user: UserFacts, product: ProductFacts, *, demo_batch: bool) -> Decision:
    reasons: list[dict[str, str]] = []
    def add(code: str, outcome: str) -> None:
        reasons.append({"code": code, "outcome": outcome})

    if product.source_type == "synthetic" and not demo_batch:
        add("synthetic_isolation", "blocked")
        status: DecisionStatus = "INELIGIBLE"
    elif not product.is_current or product.retired or product.verification_status != "verified":
        add("product_not_verified_current", "blocked")
        status = "REVIEW_REQUIRED"
    else:
        document = product.eligibility_rules
        outcomes = [_rule(rule, user, product) for rule in document.all]
        if document.any:
            alternatives = [_rule(rule, user, product) for rule in document.any]
            if any(result == "pass" for result, _ in alternatives):
                outcomes.append(("pass", "alternative_passed"))
            elif any(result == "missing" for result, _ in alternatives):
                outcomes.append(("missing", "alternative_unresolved"))
            else:
                outcomes.append(("fail", "alternatives_failed"))
        for outcome, code in outcomes:
            add(code, outcome)
        # Hard failures win over missing/ambiguous requirements.
        if any(outcome == "fail" for outcome, _ in outcomes):
            status = "INELIGIBLE"
        elif any(outcome == "missing" for outcome, _ in outcomes):
            status = "INSUFFICIENT_DATA"
        elif document.completeness != "complete" or document.ambiguous or document.unknown_reason or any(
            product.criterion_states.get(name) not in {"KNOWN", "NOT_APPLICABLE"} for name in DECISION_CRITERIA
        ):
            add("unresolved_product_criteria", "unknown")
            status = "REVIEW_REQUIRED"
        else:
            status = "ELIGIBLE_POTENTIAL"
    normalized = {"user": user.model_dump(mode="json"), "product_id": product.id,
                  "product_version": product.version, "rules": product.eligibility_rules.model_dump(mode="json"),
                  "engine": ENGINE_VERSION}
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Decision(user_id=user.id, batch_id=user.batch_id, product_id=product.id,
                    product_version=product.version, status=status, reasons=reasons,
                    evaluated_at=datetime.now(UTC), decision_input_sha256=digest)
