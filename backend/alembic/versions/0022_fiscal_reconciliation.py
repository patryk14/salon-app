"""fiscal reconciliation: real fiscal-printer total + kept Booksy till transactions

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("salon_days", sa.Column("fiscal_printer_total", sa.Numeric(10, 2)))
    op.add_column(
        "salon_days",
        sa.Column("recon_explained", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "register_txns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("doc", sa.String(80)),
        sa.Column("client_name", sa.String(200)),
        sa.Column("staff_name", sa.String(200)),
        sa.Column("method", sa.String(60)),
        sa.Column("inflow", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("outflow", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_register_txns_day", "register_txns", ["day"])


def downgrade() -> None:
    op.drop_table("register_txns")
    op.drop_column("salon_days", "recon_explained")
    op.drop_column("salon_days", "fiscal_printer_total")
