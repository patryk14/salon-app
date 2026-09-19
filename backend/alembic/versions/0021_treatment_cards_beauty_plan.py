"""treatment cards + beauty plan (F10)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
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
    # Reference data (rows are seeded idempotently by the app — app/cards.py).
    op.create_table(
        "card_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("session_variant", sa.String(20), nullable=False, server_default="parameters"),
        sa.Column("has_measurements", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("aftercare", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        *_ts(),
    )

    # Personal data → everything below dies with the client row (RODO erasure).
    op.create_table(
        "client_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "card_type_id",
            sa.Integer(),
            sa.ForeignKey("card_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("paper_signed_on", sa.Date()),
        sa.Column(
            "contraindications_checked", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", sa.String(255)),
        *_ts(),
        sa.UniqueConstraint("client_id", "card_type_id", name="uq_client_card_type"),
    )
    op.create_index("ix_client_cards_client", "client_cards", ["client_id"])

    op.create_table(
        "card_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("client_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("visit_id", sa.Integer(), sa.ForeignKey("visits.id", ondelete="SET NULL")),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("treatment", sa.String(200)),
        sa.Column("parameters", sa.Text()),
        sa.Column("preparation", sa.String(300)),
        sa.Column("notes", sa.Text()),
        sa.Column("performed_by_sub", sa.String(255)),
        sa.Column("performed_by_name", sa.String(200)),
        *_ts(),
    )
    op.create_index("ix_card_sessions_card", "card_sessions", ["card_id"])

    op.create_table(
        "card_measurements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("client_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("session_no", sa.Integer()),
        *[
            sa.Column(c, sa.Numeric(5, 1))
            for c in ("arms", "belly", "buttocks", "thighs", "calves", "weight")
        ],
        sa.Column("notes", sa.Text()),
        *_ts(),
    )
    op.create_index("ix_card_measurements_card", "card_measurements", ["card_id"])

    op.create_table(
        "beauty_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        *[
            sa.Column(c, sa.Text())
            for c in (
                "skin_type",
                "am_cleansing",
                "am_antioxidant",
                "am_hydration",
                "am_spf",
                "pm_cleansing",
                "pm_therapeutic",
                "pm_serum",
                "pm_cream",
                "extra_care",
                "lifestyle",
                "recommendations",
            )
        ],
        sa.Column("created_by", sa.String(255)),
        *_ts(),
    )
    op.create_index("ix_beauty_plans_client", "beauty_plans", ["client_id"])

    op.create_table(
        "beauty_plan_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("beauty_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("treatment", sa.String(200), nullable=False),
        sa.Column("sessions_planned", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sessions_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("interval_note", sa.String(100)),
        sa.Column("note", sa.Text()),
        *_ts(),
    )
    op.create_index("ix_beauty_plan_steps_plan", "beauty_plan_steps", ["plan_id"])


def downgrade() -> None:
    for table in (
        "beauty_plan_steps",
        "beauty_plans",
        "card_measurements",
        "card_sessions",
        "client_cards",
        "card_types",
    ):
        op.drop_table(table)
