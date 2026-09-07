"""settlement: employees, aliases, decision log, periods, lines

Seeds the real staff roster (FTE per owner: Klaudia/Karola/Oliwia 1.0, Julia
now 1.0, Hania 0.5, Weronika former) with Booksy-name aliases, and the owner's
commission rulings as the initial decision log.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-07
"""

from datetime import date

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False, unique=True),
        sa.Column("fte_factor", sa.Numeric(4, 2), nullable=False, server_default="1.0"),
        sa.Column("pay_type", sa.String(20), nullable=False, server_default="hourly"),
        sa.Column("hourly_rate", sa.Numeric(6, 2), nullable=False, server_default="31.40"),
        sa.Column("active_from", sa.Date(), nullable=True),
        sa.Column("active_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "employee_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alias", sa.String(200), nullable=False, unique=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )

    decisions = op.create_table(
        "commission_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decided_on", sa.Date(), nullable=False),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("ruling", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "settlement_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year_month", sa.String(7), nullable=False, unique=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "settlement_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "period_id",
            sa.Integer(),
            sa.ForeignKey("settlement_periods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("booksy_services", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("booksy_sales", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("notebook_services", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("cash_services", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("notebook_sales", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("cash_sales", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("hours", sa.Numeric(7, 2), nullable=False, server_default="0"),
        sa.Column("frozen_fte_factor", sa.Numeric(4, 2), nullable=False),
        sa.Column("frozen_hourly_rate", sa.Numeric(6, 2), nullable=False),
        sa.Column("frozen_scheme", sa.JSON(), nullable=False),
        sa.Column("services_base", sa.Numeric(10, 2), nullable=False),
        sa.Column("sales_base", sa.Numeric(10, 2), nullable=False),
        sa.Column("services_rate", sa.Numeric(4, 3), nullable=False),
        sa.Column("services_commission", sa.Numeric(10, 2), nullable=False),
        sa.Column("sales_commission", sa.Numeric(10, 2), nullable=False),
        sa.Column("hours_pay", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_payout", sa.Numeric(10, 2), nullable=False),
        sa.Column("override_total", sa.Numeric(10, 2), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_settlement_lines_period_employee",
        "settlement_lines",
        ["period_id", "employee_id"],
        unique=True,
    )

    # --- seed the roster (FTE per owner rulings) + Booksy-name aliases --------
    roster = [
        # display_name, fte, pay_type, aliases, active_to
        ("Klaudia", "1.0", "uop_plus_extra", ["Klaudia"], None),
        ("Karola", "1.0", "hourly", ["Karola", "Karolina"], None),
        ("Oliwia", "1.0", "hourly", ["Oliwia"], None),
        ("Julia", "1.0", "hourly", ["Julia", "Julka"], None),  # moved 0.75 -> 1.0
        ("Hania", "0.5", "hourly", ["Hania", "Hanna"], None),
        ("Weronika", "1.0", "hourly", ["Weronika"], date(2026, 3, 31)),  # former
    ]
    conn = op.get_bind()
    for name, fte, pay_type, alias_list, active_to in roster:
        emp_id = conn.execute(
            sa.text(
                "INSERT INTO employees (display_name, fte_factor, pay_type, hourly_rate, active_to) "
                "VALUES (:n, :f, :p, '31.40', :a) RETURNING id"
            ),
            {"n": name, "f": fte, "p": pay_type, "a": active_to},
        ).scalar_one()
        for alias in alias_list:
            conn.execute(
                sa.text("INSERT INTO employee_aliases (alias, employee_id) VALUES (:al, :e)"),
                {"al": alias, "e": emp_id},
            )

    op.bulk_insert(
        decisions,
        [
            {
                "decided_on": date(2026, 9, 6),
                "topic": "Progi = tabela bazowa × etat",
                "ruling": "Progi prowizji usługowej to jedna tabela bazowa (pełny etat) skalowana współczynnikiem etatu. Hania 0.5, pozostałe 1.0. Formuła w arkuszu Hani była błędna.",
                "decided_by": "wlascicielka",
            },
            {
                "decided_on": date(2026, 9, 6),
                "topic": "Prowizja sprzedażowa",
                "ruling": "Sprzedaż >= 1500 zł → 10% od całości (1541 → 154.10), poniżej 0.",
                "decided_by": "wlascicielka",
            },
            {
                "decided_on": date(2026, 9, 6),
                "topic": "Zaokrąglanie wypłat",
                "ruling": "Zawsze w górę do pełnej złotówki (1314.90 → 1315).",
                "decided_by": "wlascicielka",
            },
            {
                "decided_on": date(2026, 9, 6),
                "topic": "Pakiety i gotówka",
                "ruling": "Usługi z zeszytu (pakiet/voucher) i gotówki wliczane do bazy usługowej wykonawczyni; pakiet po cenie pakietowej.",
                "decided_by": "wlascicielka",
            },
            {
                "decided_on": date(2026, 9, 6),
                "topic": "Godziny / pensja podstawowa",
                "ruling": "Każdy pracownik wpisuje godziny; podstawa = godziny × 31.40 zł. Klaudia UoP — pensja od księgowej, w appce tylko dodatkowe godziny.",
                "decided_by": "wlascicielka",
            },
            {
                "decided_on": date(2026, 9, 7),
                "topic": "Nowy próg 12%",
                "ruling": "Utarg usługowy powyżej 15000 zł → 12% (skalowane etatem). Zmienia wypłatę np. Oliwii.",
                "decided_by": "wlascicielka",
            },
            {
                "decided_on": date(2026, 9, 7),
                "topic": "Julia — pełny etat",
                "ruling": "Julia przeszła z 3/4 na pełny etat; progi liczone jak dla pełnego etatu.",
                "decided_by": "wlascicielka",
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_settlement_lines_period_employee", table_name="settlement_lines")
    op.drop_table("settlement_lines")
    op.drop_table("settlement_periods")
    op.drop_table("commission_decisions")
    op.drop_table("employee_aliases")
    op.drop_table("employees")
