"""ledger_entries.service_name

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ledger_entries", sa.Column("service_name", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("ledger_entries", "service_name")
