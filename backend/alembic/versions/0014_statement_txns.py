"""bank statement staging (MT940 import)

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_txns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_ref", sa.String(40), nullable=False, unique=True),
        sa.Column("year_month", sa.String(7), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("counterparty", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("category", sa.String(40)),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("bucket", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("expense_id", sa.Integer(), sa.ForeignKey("expenses.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_statement_txns_month_status", "statement_txns", ["year_month", "status"])


def downgrade() -> None:
    op.drop_index("ix_statement_txns_month_status", table_name="statement_txns")
    op.drop_table("statement_txns")
