"""RODO: anonymised visits placeholder + erased-name suppression list

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("is_anonymous", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "erased_names",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("salt", sa.String(32), nullable=False),
        sa.Column("name_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("erased_on", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("erased_names")
    op.drop_column("clients", "is_anonymous")
