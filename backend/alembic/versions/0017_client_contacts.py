"""client contacts + consents from Booksy (F7 v2)

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("booksy_customer_id", sa.BigInteger()))
    op.add_column(
        "clients",
        sa.Column("marketing_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "clients",
        sa.Column("privacy_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_clients_booksy_customer_id", "clients", ["booksy_customer_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_clients_booksy_customer_id", table_name="clients")
    op.drop_column("clients", "privacy_consent")
    op.drop_column("clients", "marketing_consent")
    op.drop_column("clients", "booksy_customer_id")
