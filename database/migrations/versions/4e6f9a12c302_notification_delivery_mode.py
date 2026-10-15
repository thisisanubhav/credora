"""Distinguish local mock acceptance from SES acceptance.

Revision ID: 4e6f9a12c302
Revises: 8a9d6c2e15b0
"""

import sqlalchemy as sa
from alembic import op

revision = "4e6f9a12c302"
down_revision = "8a9d6c2e15b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification_logs", sa.Column("delivery_mode", sa.Text(), nullable=False,
                                                   server_default=sa.text("'mock'")))
    op.create_check_constraint("ck_notification_logs_delivery_mode", "notification_logs",
                               "delivery_mode IN ('mock','ses')")
    op.drop_constraint("ck_notification_logs_status", "notification_logs", type_="check")
    op.create_check_constraint("ck_notification_logs_status", "notification_logs",
                               "status IN ('reserved','sending','sent','failed','ambiguous','mocked')")


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM notification_logs WHERE status = 'mocked')")).scalar_one():
        raise RuntimeError("Mock notifications exist; explicit cleanup required before downgrade")
    op.drop_constraint("ck_notification_logs_status", "notification_logs", type_="check")
    op.create_check_constraint("ck_notification_logs_status", "notification_logs",
                               "status IN ('reserved','sending','sent','failed','ambiguous')")
    op.drop_constraint("ck_notification_logs_delivery_mode", "notification_logs", type_="check")
    op.drop_column("notification_logs", "delivery_mode")
