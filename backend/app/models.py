"""ORM models — SQLAlchemy 2.0 typed declarative style.

Schema changes go through Alembic migrations (alembic/), never create_all in
production code paths. GDPR note: Client rows and Photo objects are personal
data — deletion endpoints must remove both the row and the S3 object.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow, nullable=False
    )


class Client(TimestampMixin, Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    # Phone is the natural key at the salon front desk (Booksy exports carry it too),
    # but data quality is unknown — unique is deliberately NOT enforced yet.
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    notes: Mapped[str | None] = mapped_column(Text)

    visits: Mapped[list["Visit"]] = relationship(
        back_populates="client", cascade="all, delete-orphan", passive_deletes=True
    )
    photos: Mapped[list["Photo"]] = relationship(
        back_populates="client", cascade="all, delete-orphan", passive_deletes=True
    )


class Visit(TimestampMixin, Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    service_name: Mapped[str] = mapped_column(String(200))
    # Stored as a decimal in PLN. Free-form statuses invite typos; the API layer
    # validates against VisitStatus, the column stays a plain string.
    price_pln: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    # Booksy report row identity — the idempotency key for xlsx imports:
    # re-importing the same report must update rows, not duplicate them.
    booksy_ref: Mapped[str | None] = mapped_column(String(100), unique=True)
    # "Pracownik" from the Booksy report, kept as plain text — employees are
    # not an entity in this app (Booksy owns scheduling).
    staff_name: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    client: Mapped[Client] = relationship(back_populates="visits")

    __table_args__ = (Index("ix_visits_client_starts", "client_id", "starts_at"),)


class Photo(TimestampMixin, Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id", ondelete="SET NULL"))
    # Key in the private bucket (MinIO locally, S3 in AWS). The object itself is
    # served exclusively via presigned URLs — this table never stores public links.
    s3_key: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str] = mapped_column(String(100), default="image/jpeg")
    note: Mapped[str | None] = mapped_column(Text)

    client: Mapped[Client] = relationship(back_populates="photos")


# --------------------------------------------------------------- settlement (F2)
class Employee(TimestampMixin, Base):
    """A person paid by the salon. Deliberately its own entity (reversing the
    earlier 'staff_name is plain text' choice) — schedules, revenue and
    commission all hang off it. Booksy names resolve here via EmployeeAlias."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), unique=True)
    # FTE scales the commission brackets (owner ruling #1/#6): Hania 0.5,
    # Julia 0.75, full-timers 1.0.
    fte_factor: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("1.0"))
    # "hourly" = base salary is hours × rate; "uop_plus_extra" = Klaudia, whose
    # UoP base is the accountant's and only EXTRA hours are paid here.
    pay_type: Mapped[str] = mapped_column(String(20), default="hourly")
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("31.40"))
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)  # set = former employee (Weronika)

    aliases: Mapped[list["EmployeeAlias"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_active(self) -> bool:
        return self.active_to is None


class EmployeeAlias(Base):
    """Booksy display name → employee (Karolina=Karola, Hanna=Hania). An
    unmatched Booksy name is a loud import failure, never a silent orphan."""

    __tablename__ = "employee_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(200), unique=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    employee: Mapped[Employee] = relationship(back_populates="aliases")


class CommissionDecision(TimestampMixin, Base):
    """Append-only record of owner rulings on pay rules (the decision log). The
    engine refuses to guess money rules — every ambiguity resolved here, dated."""

    __tablename__ = "commission_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    decided_on: Mapped[date] = mapped_column(Date, nullable=False)
    topic: Mapped[str] = mapped_column(String(200))
    ruling: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(String(100))


class SettlementPeriod(TimestampMixin, Base):
    """One month of payroll. draft → numbers can be re-entered and recomputed;
    closed → every line is a frozen snapshot, immune to later rule changes."""

    __tablename__ = "settlement_periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    year_month: Mapped[str] = mapped_column(String(7), unique=True)  # "2026-09"
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | closed
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[str | None] = mapped_column(String(100))

    lines: Mapped[list["SettlementLine"]] = relationship(
        back_populates="period", cascade="all, delete-orphan", passive_deletes=True
    )


class SettlementLine(TimestampMixin, Base):
    """One employee's payout for one period: the raw INPUT snapshot, the FROZEN
    scheme it was computed against (so history survives rule changes), and the
    computed OUTPUTS. An admin override wins over the computed total when set."""

    __tablename__ = "settlement_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(
        ForeignKey("settlement_periods.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    # input snapshot (three revenue sources, each split services/sales, + hours)
    booksy_services: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    booksy_sales: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    notebook_services: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    cash_services: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    notebook_sales: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    cash_sales: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    hours: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("0"))

    # frozen scheme (what it was computed AGAINST — audit + history safety)
    frozen_fte_factor: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    frozen_hourly_rate: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    frozen_scheme: Mapped[dict] = mapped_column(JSON)  # brackets, thresholds as strings

    # computed outputs
    services_base: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    sales_base: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    services_rate: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    services_commission: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    sales_commission: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    hours_pay: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total_payout: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    override_total: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    override_reason: Mapped[str | None] = mapped_column(Text)

    period: Mapped[SettlementPeriod] = relationship(back_populates="lines")
    employee: Mapped[Employee] = relationship()

    __table_args__ = (
        Index("ix_settlement_lines_period_employee", "period_id", "employee_id", unique=True),
    )
