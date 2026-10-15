"""Deterministic source-evidence extraction; unknowns remain explicit."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from services.common.schemas import AmbiguousClause, EligibilityDocument, Evidence, NumericRule
from services.discovery.sources import require_source

Knowledge = Literal["KNOWN", "UNKNOWN", "NOT_APPLICABLE"]


class PageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str
    institution: str
    product_name: str
    source_url: str
    eligibility_text: str = Field(min_length=50, max_length=4500)
    interest_rate_text: str = Field(max_length=200)
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: datetime

    @model_validator(mode="after")
    def allowlisted(self) -> PageEvidence:
        source = require_source(self.source_key)
        if (self.institution, self.product_name, self.source_url) != (
            source.institution, source.product_name, source.url,
        ):
            raise ValueError("source_metadata_mismatch")
        return self


class ProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str
    institution: str
    product_name: str
    source_url: str
    retrieved_at: datetime
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_eligibility_text: str = Field(min_length=50, max_length=4500)
    interest_rate_text: str | None = None
    interest_rate_min_pct: Decimal | None = Field(default=None, ge=0, le=100)
    interest_rate_max_pct: Decimal | None = Field(default=None, ge=0, le=100)
    currency_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    min_monthly_income: Decimal | None = Field(default=None, ge=0)
    min_credit_score: int | None = Field(default=None, ge=0, le=1000)
    max_credit_score: int | None = Field(default=None, ge=0, le=1000)
    min_age: int | None = Field(default=None, ge=0, le=130)
    max_age: int | None = Field(default=None, ge=0, le=130)
    eligible_employment_statuses: list[str] | None = None
    criterion_states: dict[str, Knowledge]
    eligibility_rules: EligibilityDocument
    extraction_method: Literal["deterministic", "gemini", "mixed"] = "deterministic"
    model_name: str | None = None
    prompt_version: str | None = None
    verification_status: Literal["verified", "review_required", "invalid"] = "review_required"


def extract_deterministic(page: PageEvidence) -> ProductCandidate:
    text = page.eligibility_text
    rate = page.interest_rate_text
    rate_match = re.search(r"starting from\s*(\d+(?:\.\d+)?)%", rate, re.IGNORECASE)
    rate_min = Decimal(rate_match.group(1)) if rate_match else None
    if rate_min is not None and rate_min > 100:
        rate_min = None
    age_match = re.search(r"Age:\s*(\d{1,3})\s*[-–]\s*(\d{1,3})\s*years", text, re.IGNORECASE)
    if age_match is None:
        age_match = re.search(r"Minimum age of\s*(\d{1,3})\s*years", text, re.IGNORECASE)
    age_min = int(age_match.group(1)) if age_match else None
    if age_min is not None and age_min > 130:
        age_min = None
        age_match = None
    rules: list[Any] = []
    if age_match and age_min is not None:
        quote = age_match.group(0)
        rules.append(NumericRule(field="age", operator="gte", value=str(age_min), unit="years",
                                 evidence=Evidence(quote=quote, source_url=HttpUrl(page.source_url))))
    # The published sections contain conditional income and profile requirements.
    # Keep the entire bounded excerpt as a qualitative condition: a numeric minimum
    # for one branch is not a universal eligibility threshold.
    excerpt = text[:900]
    ambiguous = [AmbiguousClause(text=excerpt, evidence=Evidence(quote=excerpt, source_url=HttpUrl(page.source_url)))]
    document = EligibilityDocument(
        schema_version=1, completeness="unknown", all=rules, any=[], ambiguous=ambiguous,
        unknown_reason="Published conditions depend on profile data absent from the upload CSV",
    )
    states: dict[str, Knowledge] = {
        "interest_rate": "KNOWN" if rate_min is not None else "UNKNOWN",
        "interest_rate_period": "KNOWN" if "p.a." in rate.lower() else "UNKNOWN",
        "currency": "KNOWN" if "₹" in text else "UNKNOWN",
        "minimum_monthly_income": "UNKNOWN",
        "minimum_credit_score": "UNKNOWN",
        "maximum_credit_score": "UNKNOWN",
        "minimum_age": "KNOWN" if age_min is not None else "UNKNOWN",
        "maximum_age": "UNKNOWN",
        "employment_requirements": "KNOWN" if "Employees" in text or "employees" in text else "UNKNOWN",
    }
    return ProductCandidate(
        source_key=page.source_key, institution=page.institution, product_name=page.product_name,
        source_url=page.source_url, retrieved_at=page.retrieved_at,
        source_content_sha256=page.source_content_sha256, raw_eligibility_text=text,
        interest_rate_text=rate or None, interest_rate_min_pct=rate_min,
        currency_code="INR" if states["currency"] == "KNOWN" else None,
        min_age=age_min, criterion_states=states, eligibility_rules=document,
    )


def validate_candidate(candidate: ProductCandidate, page: PageEvidence) -> ProductCandidate:
    if candidate.source_key != page.source_key or candidate.source_url != page.source_url:
        raise ValueError("candidate_source_mismatch")
    if candidate.source_content_sha256 != page.source_content_sha256:
        raise ValueError("candidate_source_hash_mismatch")
    if candidate.raw_eligibility_text != page.eligibility_text:
        raise ValueError("candidate_evidence_mismatch")
    expected_hash = hashlib.sha256((page.eligibility_text + "\n" + page.interest_rate_text).encode()).hexdigest()
    if page.source_content_sha256 != expected_hash:
        raise ValueError("page_evidence_hash_mismatch")
    for item in candidate.eligibility_rules.all + candidate.eligibility_rules.any:
        if item.evidence.quote not in page.eligibility_text:
            raise ValueError("rule_evidence_not_in_source")
        if isinstance(item, NumericRule):
            numbers = item.value if isinstance(item.value, tuple) else (item.value,)
            if any(number not in item.evidence.quote for number in numbers):
                raise ValueError("rule_value_not_in_evidence")
    for clause in candidate.eligibility_rules.ambiguous:
        if clause.evidence.quote not in page.eligibility_text:
            raise ValueError("ambiguous_evidence_not_in_source")
    if candidate.interest_rate_min_pct is not None:
        value = str(candidate.interest_rate_min_pct)
        if value not in page.interest_rate_text:
            raise ValueError("interest_rate_not_in_source")
    if candidate.currency_code == "INR" and "₹" not in page.eligibility_text:
        raise ValueError("currency_not_in_source")
    if candidate.min_age is not None and candidate.criterion_states.get("minimum_age") != "KNOWN":
        raise ValueError("age_state_mismatch")
    if candidate.verification_status == "verified":
        candidate.eligibility_rules.require_auto_matchable()
    return candidate
