"""salon_day: daily cash reconciliation (Day 2)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-12
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "salon_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False, unique=True),
        sa.Column("booksy_cash", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("fiscal_register", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("salon_days")
