"""notebook: prepaid (package/voucher) visits

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebook_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("service_name", sa.String(200), nullable=False),
        sa.Column("amount_pln", sa.Numeric(10, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_notebook_employee_date", "notebook_entries", ["employee_id", "entry_date"])


def downgrade() -> None:
    op.drop_index("ix_notebook_employee_date", table_name="notebook_entries")
    op.drop_table("notebook_entries")
