"""Add upload idempotency/recovery metadata and source-faithful user fields.

Revision ID: 8dcb247a9f10
Revises: cb5ec7ae0e62
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8dcb247a9f10"
down_revision = "cb5ec7ae0e62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("upload_batches", sa.Column("idempotency_key_hash", sa.String(64)))
    op.add_column("upload_batches", sa.Column("request_fingerprint", sa.String(64)))
    op.add_column("upload_batches", sa.Column("processing_token", postgresql.UUID(as_uuid=True)))
    op.add_column("upload_batches", sa.Column("processing_lease_expires_at", postgresql.TIMESTAMP(timezone=True)))
    op.create_unique_constraint("uq_upload_batches_idempotency_key_hash", "upload_batches", ["idempotency_key_hash"])
    op.create_check_constraint("ck_upload_batches_idempotency_hash", "upload_batches", "idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'")
    op.create_check_constraint("ck_upload_batches_fingerprint", "upload_batches", "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'")
    op.add_column("users", sa.Column("employment_status_raw", sa.Text()))
    op.alter_column("users", "income_currency", existing_type=sa.String(3), nullable=True)
    op.create_check_constraint("ck_users_employment_raw", "users", "employment_status_raw IS NULL OR char_length(employment_status_raw) BETWEEN 1 AND 128")


def downgrade() -> None:
    op.drop_constraint("ck_users_employment_raw", "users", type_="check")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM users WHERE income_currency IS NULL) THEN RAISE EXCEPTION 'Cannot downgrade: users have unspecified currency'; END IF; END $$")
    op.alter_column("users", "income_currency", existing_type=sa.String(3), nullable=False)
    op.drop_column("users", "employment_status_raw")
    op.drop_constraint("ck_upload_batches_fingerprint", "upload_batches", type_="check")
    op.drop_constraint("ck_upload_batches_idempotency_hash", "upload_batches", type_="check")
    op.drop_constraint("uq_upload_batches_idempotency_key_hash", "upload_batches", type_="unique")
    op.drop_column("upload_batches", "processing_lease_expires_at")
    op.drop_column("upload_batches", "processing_token")
    op.drop_column("upload_batches", "request_fingerprint")
    op.drop_column("upload_batches", "idempotency_key_hash")
