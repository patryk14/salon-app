"""day 1 modules: supply list, staff documents, availability, time off

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _ts(*extra: sa.Column) -> list[sa.Column]:
    return [
        *extra,
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "supply_items",
        *_ts(
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="to_buy"),
            sa.Column("note", sa.Text()),
            sa.Column("created_by", sa.String(100)),
            sa.Column("bought_at", sa.DateTime(timezone=True)),
        ),
    )
    op.create_table(
        "staff_documents",
        *_ts(
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "employee_id",
                sa.Integer(),
                sa.ForeignKey("employees.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("doc_type", sa.String(20), nullable=False, server_default="umowa"),
            sa.Column("title", sa.String(200)),
            sa.Column("valid_until", sa.Date()),
            sa.Column("note", sa.Text()),
        ),
    )
    op.create_index("ix_staff_documents_employee", "staff_documents", ["employee_id"])
    op.create_table(
        "availabilities",
        *_ts(
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "employee_id",
                sa.Integer(),
                sa.ForeignKey("employees.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("work_date", sa.Date(), nullable=False),
            sa.Column("from_time", sa.Time()),
            sa.Column("to_time", sa.Time()),
            sa.Column("note", sa.Text()),
        ),
    )
    op.create_index(
        "ix_availability_employee_date",
        "availabilities",
        ["employee_id", "work_date"],
        unique=True,
    )
    op.create_table(
        "time_off",
        *_ts(
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "employee_id",
                sa.Integer(),
                sa.ForeignKey("employees.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="urlop"),
            sa.Column("status", sa.String(10), nullable=False, server_default="requested"),
            sa.Column("note", sa.Text()),
        ),
    )
    op.create_index("ix_time_off_employee", "time_off", ["employee_id", "start_date"])


def downgrade() -> None:
    op.drop_table("time_off")
    op.drop_table("availabilities")
    op.drop_table("staff_documents")
    op.drop_table("supply_items")
