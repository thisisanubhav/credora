"""Keep the one-row SES demo fixture compatible with real ingestion validation."""

import pytest

from services.ingestion.worker import validate_row


@pytest.mark.parametrize(("domain", "accepted"), [("example.com", True), ("example.test", False)])
def test_synthetic_preparation_email_domain(domain: str, accepted: bool) -> None:
    row = {
        "user_id": "synthetic-preparation-regression",
        "email": f"synthetic@{domain}",
        "monthly_income": "50000",
        "credit_score": "710",
        "employment_status": "Salaried",
        "age": "30",
    }
    user, errors = validate_row(row)
    if accepted:
        assert user is not None
        assert errors == []
        assert user["employment_status"] == "salaried"
    else:
        assert user is None
        assert errors == ["invalid_email"]
