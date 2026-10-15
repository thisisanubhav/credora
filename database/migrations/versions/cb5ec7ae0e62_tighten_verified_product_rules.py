"""tighten verified product rules

Revision ID: cb5ec7ae0e62
Revises: 1d98b8c6edf1
"""
from collections.abc import Sequence

from alembic import op

revision: str = "cb5ec7ae0e62"
down_revision: str | None = "1d98b8c6edf1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Alembic does not autogenerate CHECK-constraint changes; these are explicit.
    op.create_check_constraint(
        "ck_loan_products_rate_max",
        "loan_products",
        "interest_rate_max_pct IS NULL OR interest_rate_max_pct >= 0",
    )
    op.create_check_constraint(
        "ck_loan_products_verified_rules",
        "loan_products",
        "verification_status <> 'verified' OR COALESCE(("
        "eligibility_rules->>'completeness' = 'complete' "
        "AND jsonb_typeof(eligibility_rules->'all') = 'array' "
        "AND jsonb_typeof(eligibility_rules->'any') = 'array' "
        "AND jsonb_typeof(eligibility_rules->'ambiguous') = 'array' "
        "AND (jsonb_array_length(eligibility_rules->'all') + "
        "jsonb_array_length(eligibility_rules->'any') + "
        "jsonb_array_length(eligibility_rules->'ambiguous')) > 0), false)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_loan_products_verified_rules", "loan_products", type_="check")
    op.drop_constraint("ck_loan_products_rate_max", "loan_products", type_="check")
