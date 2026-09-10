"""identity: user_account bridge + invite (F6 staff portal)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-10
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cognito_sub", sa.String(64), nullable=False, unique=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE")),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE")),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(role = 'staff' AND employee_id IS NOT NULL AND client_id IS NULL) "
            "OR (role = 'client' AND client_id IS NOT NULL AND employee_id IS NULL) "
            "OR (role = 'admin' AND employee_id IS NULL AND client_id IS NULL)",
            name="ck_user_account_one_link",
        ),
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE")),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_by_sub", sa.String(64)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("invites")
    op.drop_table("user_accounts")
