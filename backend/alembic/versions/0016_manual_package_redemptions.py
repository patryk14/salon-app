"""manual package redemptions + performer-assignment audit

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "package_redemptions",
        sa.Column("source", sa.String(12), nullable=False, server_default="booksy"),
    )
    op.add_column("package_redemptions", sa.Column("note", sa.Text()))
    op.add_column("package_redemptions", sa.Column("created_by", sa.String(100)))
    op.add_column("package_redemptions", sa.Column("assigned_by", sa.String(100)))
    # Manual redemptions have no Booksy document number. SQLite can't ALTER COLUMN
    # (and tests build the schema from the model, already nullable), so only the
    # real Postgres target needs the widening.
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column(
            "package_redemptions", "booksy_ref", existing_type=sa.String(40), nullable=True
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column(
            "package_redemptions", "booksy_ref", existing_type=sa.String(40), nullable=False
        )
    op.drop_column("package_redemptions", "assigned_by")
    op.drop_column("package_redemptions", "created_by")
    op.drop_column("package_redemptions", "note")
    op.drop_column("package_redemptions", "source")
