"""Isolate synthetic demonstrations and support matching completion events.

Revision ID: 8a9d6c2e15b0
Revises: 5f16aa35b814
"""

import sqlalchemy as sa
from alembic import op

revision = "8a9d6c2e15b0"
down_revision = "5f16aa35b814"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("upload_batches", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("product_sources", sa.Column("source_type", sa.Text(), nullable=False, server_default=sa.text("'official'")))
    op.create_check_constraint("ck_product_sources_type", "product_sources", "source_type IN ('official','synthetic')")
    op.drop_constraint("ck_outbox_events_type", "outbox_events", type_="check")
    op.create_check_constraint("ck_outbox_events_type", "outbox_events", "event_type IN ('upload_batch.ready.v1','matching.completed.v1')")


def downgrade() -> None:
    # Reject downgrade if M5-only data would be misclassified or dropped.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM upload_batches WHERE is_demo) OR EXISTS (SELECT 1 FROM product_sources WHERE source_type = 'synthetic') OR EXISTS (SELECT 1 FROM outbox_events WHERE event_type = 'matching.completed.v1')")).scalar_one():
        raise RuntimeError("M5 demo/completion data exists; explicit cleanup is required before downgrade")
    op.drop_constraint("ck_outbox_events_type", "outbox_events", type_="check")
    op.create_check_constraint("ck_outbox_events_type", "outbox_events", "event_type = 'upload_batch.ready.v1'")
    op.drop_constraint("ck_product_sources_type", "product_sources", type_="check")
    op.drop_column("product_sources", "source_type")
    op.drop_column("upload_batches", "is_demo")
