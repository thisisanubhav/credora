"""Persist source-supported currency and explicit criterion knowledge states.

Revision ID: 5f16aa35b814
Revises: 2f2c8b144bee
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5f16aa35b814"
down_revision = "2f2c8b144bee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("loan_products", sa.Column("currency_code", sa.String(3)))
    op.add_column("loan_products", sa.Column("criterion_states", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_check_constraint("ck_loan_products_currency", "loan_products", "currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'")
    op.create_check_constraint("ck_loan_products_criterion_states", "loan_products", "jsonb_typeof(criterion_states) = 'object'")


def downgrade() -> None:
    op.drop_constraint("ck_loan_products_criterion_states", "loan_products", type_="check")
    op.drop_constraint("ck_loan_products_currency", "loan_products", type_="check")
    op.drop_column("loan_products", "criterion_states")
    op.drop_column("loan_products", "currency_code")
