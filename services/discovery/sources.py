"""Only these reviewed official pages may be fetched by Workflow A."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDefinition:
    key: str
    institution: str
    product_name: str
    url: str
    eligibility_start: str
    eligibility_end: str

    @property
    def origin(self) -> str:
        from urllib.parse import urlsplit

        parts = urlsplit(self.url)
        return f"{parts.scheme}://{parts.netloc}"


SOURCES: dict[str, SourceDefinition] = {
    "sbi": SourceDefinition(
        key="sbi", institution="State Bank of India", product_name="SBI Personal Loan",
        url="https://sbi.bank.in/web/personal-banking/loans/personal-loans/sbi-personal-loan",
        eligibility_start="Eligibility Employees working with",
        eligibility_end="Terms and Conditions",
    ),
    "axis": SourceDefinition(
        key="axis", institution="Axis Bank", product_name="Axis Bank Personal Loan",
        url="https://www.axis.bank.in/loans/personal-loan",
        eligibility_start="Personal Loan eligibility Salaried Employees",
        eligibility_end="Documents required for Personal Loan",
    ),
}


def require_source(key: str) -> SourceDefinition:
    try:
        return SOURCES[key]
    except KeyError as error:
        raise ValueError("source_not_allowlisted") from error
