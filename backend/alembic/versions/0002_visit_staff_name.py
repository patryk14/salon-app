"""add visits.staff_name (Booksy 'Pracownik' column)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-06
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("visits", sa.Column("staff_name", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("visits", "staff_name")
