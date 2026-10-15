"""Associate AWS upload batches with a verified API Gateway JWT subject.

Revision ID: 74d95e91acb2
Revises: 4e6f9a12c302
"""

import sqlalchemy as sa
from alembic import op

revision = "74d95e91acb2"
down_revision = "4e6f9a12c302"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable preserves existing local batches; AWS mode requires a subject in application code.
    op.add_column("upload_batches", sa.Column("owner_subject", sa.String(length=255), nullable=True))
    op.create_check_constraint(
        "ck_upload_batches_owner_subject", "upload_batches",
        "owner_subject IS NULL OR char_length(owner_subject) BETWEEN 1 AND 255",
    )


def downgrade() -> None:
    op.drop_constraint("ck_upload_batches_owner_subject", "upload_batches", type_="check")
    op.drop_column("upload_batches", "owner_subject")
