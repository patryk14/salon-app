"""expenses & P&L (F12)

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

# The owner's cost columns (id fixed so the recurring seed can reference them).
_CATEGORIES = [
    (1, "koszty_stale", "Koszty stałe", 1),
    (2, "koszty_zmienne", "Koszty zmienne", 2),
    (3, "koszty_jednorazowe", "Koszty art. jednorazowe", 3),
    (4, "paznokcie", "Paznokcie", 4),
    (5, "kosmetologia", "Kosmetologia", 5),
    (6, "kosmetyki_odsprzedaz", "Kosmetyki odsprzedaż", 6),
]

# Real fixed-cost lines from the owner's sheet (all under Koszty stałe). Amounts
# are defaults the owner adjusts per month; a month materializes them once.
_RECURRING = [
    ("Najem", "5840"),
    ("Telefon leasing", "120"),
    ("RF leasing", "1900"),
    ("Telefon", "184"),
    ("Muzyka", "74"),
    ("Leasing Primelle", "1200"),
    ("Odpady medyczne", "72"),
    ("Booksy", "350"),
    ("Księgowa", "1020"),
    ("Rachunki", "1500"),
    ("Ubezpieczenie", "150"),
    ("Klaudia (UOP: ZUS + podatek)", "2262"),
    ("ZUS", "1800"),
    ("Internet", "70"),
    ("Canva", "50"),
]


def upgrade() -> None:
    ts = dict(
        created_at=dict(server_default=sa.func.now(), nullable=False),
        updated_at=dict(server_default=sa.func.now(), nullable=False),
    )
    categories = op.create_table(
        "expense_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts["created_at"]),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts["updated_at"]),
    )
    recurring = op.create_table(
        "recurring_expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("expense_categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("amount_pln", sa.Numeric(10, 2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts["created_at"]),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts["updated_at"]),
    )
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year_month", sa.String(7), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("expense_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("amount_pln", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("vendor", sa.String(120)),
        sa.Column("source", sa.String(12), nullable=False, server_default="manual"),
        sa.Column("incurred_on", sa.Date()),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts["created_at"]),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts["updated_at"]),
    )
    op.create_index("ix_expenses_month_cat", "expenses", ["year_month", "category_id"])
    op.create_table(
        "pnl_months",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year_month", sa.String(7), nullable=False, unique=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("revenue_override", sa.Numeric(10, 2)),
        sa.Column("staff_cost_override", sa.Numeric(10, 2)),
        sa.Column("revenue_snapshot", sa.Numeric(10, 2)),
        sa.Column("staff_cost_snapshot", sa.Numeric(10, 2)),
        sa.Column("note", sa.Text()),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_by", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts["created_at"]),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts["updated_at"]),
    )

    op.bulk_insert(
        categories,
        [{"id": i, "code": c, "name": n, "display_order": o} for i, c, n, o in _CATEGORIES],
    )
    op.bulk_insert(
        recurring,
        [{"category_id": 1, "name": name, "amount_pln": amt} for name, amt in _RECURRING],
    )


def downgrade() -> None:
    op.drop_table("pnl_months")
    op.drop_index("ix_expenses_month_cat", table_name="expenses")
    op.drop_table("expenses")
    op.drop_table("recurring_expenses")
    op.drop_table("expense_categories")
