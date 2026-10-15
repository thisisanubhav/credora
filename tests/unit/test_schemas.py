"""Contract tests keep unknown and unsupported criteria out of auto-matching."""

import pytest
from pydantic import ValidationError

from services.common.schemas import EligibilityDocument

EVIDENCE = {"quote": "Minimum monthly income: 1,000 USD", "source_url": "https://fixture.invalid/loan"}
RULE = {
    "field": "monthly_income", "operator": "gte", "value": "1000.00",
    "unit": "USD/month", "evidence": EVIDENCE,
}


def test_complete_source_grounded_rule():
    criteria = EligibilityDocument.model_validate({
        "schema_version": 1, "completeness": "complete", "all": [RULE],
    })
    criteria.require_auto_matchable()
    assert criteria.all[0].field == "monthly_income"


@pytest.mark.parametrize("rule", [
    {**RULE, "operator": "invented"},
    {**RULE, "value": "NaN"},
    {**RULE, "value": "-1"},
    {**RULE, "unit": "USD/year"},
    {**RULE, "evidence": {"quote": "", "source_url": "https://fixture.invalid/loan"}},
    {**RULE, "extra_claim": "approved"},
    {**RULE, "operator": "between", "value": ["2000", "1000"]},
])
def test_unsupported_rule_rejected(rule):
    with pytest.raises(ValidationError):
        EligibilityDocument.model_validate({
            "schema_version": 1, "completeness": "complete", "all": [rule],
        })


def test_unknown_and_ambiguous_fail_closed():
    unknown = EligibilityDocument.model_validate({
        "schema_version": 1, "completeness": "unknown",
        "unknown_reason": "source does not state a score threshold",
    })
    with pytest.raises(ValueError):
        unknown.require_auto_matchable()
    ambiguous = EligibilityDocument.model_validate({
        "schema_version": 1, "completeness": "complete", "all": [RULE],
        "ambiguous": [{"text": "subject to lender review", "evidence": EVIDENCE}],
    })
    with pytest.raises(ValueError):
        ambiguous.require_auto_matchable()


def test_empty_complete_document_rejected():
    with pytest.raises(ValidationError):
        EligibilityDocument.model_validate({"schema_version": 1, "completeness": "complete"})
