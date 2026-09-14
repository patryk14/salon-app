"""vouchers (gift cards) + redemptions

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vouchers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("total_value", sa.Numeric(10, 2), nullable=False),
        sa.Column("remaining_value", sa.Numeric(10, 2), nullable=False),
        sa.Column("purchased_on", sa.Date()),
        sa.Column("valid_until", sa.Date()),
        sa.Column("note", sa.Text()),
        sa.Column("source", sa.String(12), nullable=False, server_default="manual"),
        sa.Column("created_by", sa.String(100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "voucher_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "voucher_id",
            sa.Integer(),
            sa.ForeignKey("vouchers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("redeemed_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", sa.String(100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_voucher_redemptions_voucher", "voucher_redemptions", ["voucher_id"])


def downgrade() -> None:
    op.drop_index("ix_voucher_redemptions_voucher", table_name="voucher_redemptions")
    op.drop_table("voucher_redemptions")
    op.drop_table("vouchers")
