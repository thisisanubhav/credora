"""Persist complete PII-free row rejection metadata.

Revision ID: 2f2c8b144bee
Revises: 8dcb247a9f10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "2f2c8b144bee"
down_revision = "8dcb247a9f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_row_errors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("upload_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("upload_batches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("codes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("upload_batch_id", "row_number", name="uq_upload_row_errors_batch_row"),
        sa.CheckConstraint("row_number > 1", name="ck_upload_row_errors_row_number"),
        sa.CheckConstraint("jsonb_typeof(codes) = 'array' AND jsonb_array_length(codes) > 0", name="ck_upload_row_errors_codes"),
    )


def downgrade() -> None:
    op.drop_table("upload_row_errors")
