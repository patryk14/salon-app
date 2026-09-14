"""package redemptions (Booksy 'Pakiet' till transactions → commission)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "package_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booksy_ref", sa.String(40), nullable=False, unique=True),
        sa.Column("package_id", sa.Integer(), sa.ForeignKey("packages.id", ondelete="SET NULL")),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("redemption_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_package_redemptions_emp_date", "package_redemptions", ["employee_id", "redemption_date"]
    )


def downgrade() -> None:
    op.drop_table("package_redemptions")
