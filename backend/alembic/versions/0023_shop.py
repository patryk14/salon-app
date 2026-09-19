"""shop: products, stock movements, sales (→ commission), pickup orders (F11)

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def _ts() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    # Fiscal reconciliation follow-up (0022 is already deployed): an explanation
    # belongs to the gap AMOUNT it explained, and its text is admin-only.
    op.add_column("salon_days", sa.Column("recon_explained_gap", sa.Numeric(10, 2)))
    op.add_column("salon_days", sa.Column("recon_note", sa.Text()))

    op.add_column(
        "settlement_lines",
        sa.Column("shop_sales", sa.Numeric(10, 2), nullable=False, server_default="0"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("brand", sa.String(100)),
        sa.Column("description", sa.Text()),
        sa.Column("price_pln", sa.Numeric(8, 2), nullable=False),
        sa.Column("stock_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(255)),
        *_ts(),
        sa.CheckConstraint("stock_qty >= 0", name="ck_products_stock_nonneg"),
    )
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("ref", sa.String(40)),
        sa.Column("note", sa.Text()),
        sa.Column("created_by_sub", sa.String(255)),
        sa.Column("created_by_name", sa.String(200)),
        *_ts(),
    )
    op.create_index("ix_stock_movements_product", "stock_movements", ["product_id"])
    op.create_table(
        "shop_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(12), nullable=False, server_default="placed"),
        sa.Column("note", sa.Text()),
        sa.Column("handled_by_name", sa.String(200)),
        *_ts(),
    )
    op.create_index("ix_shop_orders_client", "shop_orders", ["client_id"])
    op.create_table(
        "shop_order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("shop_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("price_at_order", sa.Numeric(8, 2), nullable=False),
        *_ts(),
    )
    op.create_table(
        "product_sales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(8, 2), nullable=False),
        sa.Column("total", sa.Numeric(10, 2), nullable=False),
        sa.Column("sold_on", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(12), nullable=False, server_default="karta"),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL")),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("shop_orders.id", ondelete="SET NULL")),
        sa.Column("created_by_sub", sa.String(255)),
        *_ts(),
    )
    op.create_index("ix_product_sales_day", "product_sales", ["sold_on"])
    op.create_index("ix_product_sales_employee", "product_sales", ["employee_id", "sold_on"])


def downgrade() -> None:
    for table in (
        "product_sales",
        "shop_order_items",
        "shop_orders",
        "stock_movements",
        "products",
    ):
        op.drop_table(table)
    op.drop_column("settlement_lines", "shop_sales")
    op.drop_column("salon_days", "recon_note")
    op.drop_column("salon_days", "recon_explained_gap")
