"""Durable replay fence for internal signed requests.

Revision ID: 9187e3f76a21
Revises: 74d95e91acb2
"""

import sqlalchemy as sa
from alembic import op

revision = "9187e3f76a21"
down_revision = "74d95e91acb2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "internal_request_nonces",
        sa.Column("key_id", sa.String(32), primary_key=True),
        sa.Column("nonce", sa.String(128), primary_key=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("char_length(key_id) BETWEEN 1 AND 32", name="ck_internal_nonce_key_id"),
        sa.CheckConstraint("char_length(nonce) BETWEEN 16 AND 128", name="ck_internal_nonce_length"),
    )
    op.create_index("ix_internal_nonce_expires", "internal_request_nonces", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_internal_nonce_expires", table_name="internal_request_nonces")
    op.drop_table("internal_request_nonces")
