"""Source-grounded eligibility document contract, not a matching engine."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

NumericField = Literal["monthly_income", "credit_score", "age"]
CategoricalField = Literal["employment_status"]
EmploymentStatus = Literal[
    "salaried", "self_employed", "contract", "unemployed", "retired", "student", "other"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    quote: str = Field(min_length=1, max_length=1000)
    source_url: HttpUrl


class NumericRule(StrictModel):
    field: NumericField
    operator: Literal["gte", "lte", "between"]
    value: str | tuple[str, str]
    unit: str = Field(min_length=1, max_length=32)
    evidence: Evidence

    @model_validator(mode="after")
    def valid_numeric_value(self) -> NumericRule:
        values = self.value if isinstance(self.value, tuple) else (self.value,)
        if (self.operator == "between") != (len(values) == 2):
            raise ValueError("between needs two decimal bounds; other operators need one")
        try:
            bounds = [Decimal(value) for value in values]
        except InvalidOperation as error:
            raise ValueError("numeric values must be decimal strings") from error
        if any(not value.is_finite() or value < 0 for value in bounds):
            raise ValueError("numeric bounds must be finite and nonnegative")
        if len(bounds) == 2 and bounds[0] > bounds[1]:
            raise ValueError("numeric range is reversed")
        if self.field == "monthly_income" and not self.unit.endswith("/month"):
            raise ValueError("monthly income needs an explicit currency/month unit")
        if self.field in {"age", "credit_score"} and self.unit not in {"years", "points"}:
            raise ValueError("age and score need explicit units")
        return self


class EmploymentRule(StrictModel):
    field: CategoricalField
    operator: Literal["eq", "in"]
    value: EmploymentStatus | list[EmploymentStatus]
    evidence: Evidence

    @model_validator(mode="after")
    def valid_values(self) -> EmploymentRule:
        if self.operator == "eq" and isinstance(self.value, list):
            raise ValueError("eq needs one status")
        if self.operator == "in" and (not isinstance(self.value, list) or not self.value or len(set(self.value)) != len(self.value)):
            raise ValueError("in needs a nonempty set of distinct statuses")
        return self


class AmbiguousClause(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    evidence: Evidence


class EligibilityDocument(StrictModel):
    schema_version: Literal[1]
    completeness: Literal["complete", "unknown"]
    all: list[NumericRule | EmploymentRule] = Field(default_factory=list)
    any: list[NumericRule | EmploymentRule] = Field(default_factory=list)
    ambiguous: list[AmbiguousClause] = Field(default_factory=list)
    unknown_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def complete_is_evaluable(self) -> EligibilityDocument:
        if self.completeness == "complete" and not (self.all or self.any or self.ambiguous):
            raise ValueError("complete criteria must contain source-supported conditions")
        if self.completeness == "unknown" and not self.unknown_reason:
            raise ValueError("unknown criteria need a reason")
        return self

    def require_auto_matchable(self) -> None:
        """Reject missing or qualitative conditions until explicitly resolved."""
        if self.completeness != "complete" or self.ambiguous or self.unknown_reason:
            raise ValueError("criteria are not fully deterministic and source-grounded")
