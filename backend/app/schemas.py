"""API request/response shapes (Pydantic). ORM rows never leave the app raw."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class VisitStatus(StrEnum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


# --------------------------------------------------------------------- clients
class ClientCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    notes: str | None = None


class ClientUpdate(BaseModel):
    """PATCH semantics: only provided fields change."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    notes: str | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    phone: str | None
    email: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------- visits
class VisitCreate(BaseModel):
    starts_at: datetime
    service_name: str = Field(min_length=1, max_length=200)
    price_pln: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    status: VisitStatus = VisitStatus.scheduled
    notes: str | None = None


class VisitUpdate(BaseModel):
    starts_at: datetime | None = None
    service_name: str | None = Field(default=None, min_length=1, max_length=200)
    price_pln: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    status: VisitStatus | None = None
    notes: str | None = None


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    starts_at: datetime
    service_name: str
    price_pln: Decimal | None
    status: VisitStatus
    booksy_ref: str | None
    staff_name: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ pagination
class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------------- employees
class PayType(StrEnum):
    hourly = "hourly"
    uop_plus_extra = "uop_plus_extra"


class EmployeeCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    fte_factor: Decimal = Field(default=Decimal("1.0"), gt=0, le=1, max_digits=4, decimal_places=2)
    pay_type: PayType = PayType.hourly
    hourly_rate: Decimal = Field(default=Decimal("31.40"), ge=0, max_digits=6, decimal_places=2)
    aliases: list[str] = Field(default_factory=list)


class EmployeeUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    fte_factor: Decimal | None = Field(default=None, gt=0, le=1, max_digits=4, decimal_places=2)
    pay_type: PayType | None = None
    hourly_rate: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    active_to: date | None = None  # set = mark former employee


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    fte_factor: Decimal
    pay_type: PayType
    hourly_rate: Decimal
    active_from: date | None
    active_to: date | None
    is_active: bool


# ------------------------------------------------------------------ settlement
class SettlementInputIn(BaseModel):
    """One employee's numbers for a period. All optional → 0; the base is the
    sum of the three revenue sources per stream (services / sales)."""

    booksy_services: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    booksy_sales: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    notebook_services: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    cash_services: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    notebook_sales: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    cash_sales: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    hours: Decimal = Field(default=Decimal("0"), ge=0, max_digits=7, decimal_places=2)
    override_total: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    override_reason: str | None = None


class SettlementLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: int
    booksy_services: Decimal
    booksy_sales: Decimal
    notebook_services: Decimal
    cash_services: Decimal
    notebook_sales: Decimal
    cash_sales: Decimal
    hours: Decimal
    services_base: Decimal
    sales_base: Decimal
    services_rate: Decimal
    services_commission: Decimal
    sales_commission: Decimal
    hours_pay: Decimal
    total_payout: Decimal
    override_total: Decimal | None
    override_reason: str | None


class SettlementPeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    year_month: str
    status: str
    lines: list[SettlementLineOut] = []


class PeriodCreate(BaseModel):
    year_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")  # "2026-09"


class DecisionCreate(BaseModel):
    decided_on: date
    topic: str = Field(min_length=1, max_length=200)
    ruling: str = Field(min_length=1)
    decided_by: str = Field(min_length=1, max_length=100)


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decided_on: date
    topic: str
    ruling: str
    decided_by: str


# ---------------------------------------------------------- worklog (F3)
class TimesheetCreate(BaseModel):
    employee_id: int
    work_date: date
    hours: Decimal = Field(ge=0, le=24, max_digits=5, decimal_places=2)
    note: str | None = None


class TimesheetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    work_date: date
    hours: Decimal
    note: str | None


class LedgerCreate(BaseModel):
    employee_id: int
    entry_date: date
    amount_pln: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    note: str | None = None


class LedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    entry_date: date
    amount_pln: Decimal
    note: str | None


class DerivedSources(BaseModel):
    """What the month's timesheets + ledger sum to for one employee — the
    numbers that pre-fill a settlement line's hours and cash_services."""

    employee_id: int
    hours: Decimal
    cash_services: Decimal
