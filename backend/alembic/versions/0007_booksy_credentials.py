"""booksy_credentials (F5 auto-pull)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booksy_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.String(20), nullable=False),
        sa.Column("access_token", sa.String(200), nullable=False),
        sa.Column("api_key", sa.String(200), nullable=False),
        sa.Column("fingerprint", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("booksy_credentials")
