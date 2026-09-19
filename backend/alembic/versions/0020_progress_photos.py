"""progress photos + photo consent + RODO tombstone (F9)

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Progress-photo tagging + audit on the existing photos table.
    op.add_column("photos", sa.Column("kind", sa.String(10)))
    op.add_column("photos", sa.Column("taken_on", sa.Date()))
    op.add_column("photos", sa.Column("uploaded_by", sa.String(255)))

    # Explicit photo consent on clients (RODO): no consent → no upload.
    op.add_column(
        "clients",
        sa.Column("photo_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("clients", sa.Column("photo_consent_at", sa.DateTime(timezone=True)))

    # RODO erasure tombstones: Booksy ids we must never re-import.
    op.create_table(
        "client_tombstones",
        sa.Column("booksy_customer_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("reason", sa.String(40), nullable=False, server_default="rodo_erasure"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("client_tombstones")
    op.drop_column("clients", "photo_consent_at")
    op.drop_column("clients", "photo_consent")
    op.drop_column("photos", "uploaded_by")
    op.drop_column("photos", "taken_on")
    op.drop_column("photos", "kind")
