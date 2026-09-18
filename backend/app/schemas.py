"""API request/response shapes (Pydantic). ORM rows never leave the app raw."""

from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


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
    monthly_base_pln: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    active_to: date | None = None  # set = mark former employee


class AliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alias: str


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=200)


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    fte_factor: Decimal
    pay_type: PayType
    hourly_rate: Decimal
    monthly_base_pln: Decimal | None = None
    active_from: date | None
    active_to: date | None
    is_active: bool
    aliases: list[AliasOut] = []


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


class ReadinessWarning(BaseModel):
    employee: str
    kind: str  # no_line | empty | anomaly | unmatched_staff
    message: str


class PeriodReadiness(BaseModel):
    year_month: str
    ok: bool
    warnings: list[ReadinessWarning]


class VisitBrowseOut(BaseModel):
    """A visit for the admin visits browser — with the client's name joined in."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    starts_at: datetime
    client_name: str
    service_name: str
    staff_name: str | None
    price_pln: Decimal | None
    status: str


# ---------------------------------------------------------- worklog (F3)
MAX_HOURS_PER_DAY = 11  # owner rule: nobody logs more than 11 h in a day


class TimesheetCreate(BaseModel):
    employee_id: int
    work_date: date
    # Cap at 11 h/day (owner safeguard) — a bigger number is a typo or padding.
    hours: Decimal = Field(ge=0, le=MAX_HOURS_PER_DAY, max_digits=5, decimal_places=2)
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
    service_name: str = Field(min_length=1, max_length=200)
    amount_pln: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    note: str | None = None


class LedgerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    entry_date: date
    service_name: str | None
    amount_pln: Decimal
    note: str | None


class DerivedSources(BaseModel):
    """What the month's timesheets + ledger sum to for one employee — the
    numbers that pre-fill a settlement line's hours and cash_services."""

    employee_id: int
    hours: Decimal
    cash_services: Decimal


class NotebookCreate(BaseModel):
    employee_id: int
    entry_date: date
    service_name: str = Field(min_length=1, max_length=200)
    amount_pln: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    note: str | None = None


class NotebookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    entry_date: date
    service_name: str
    amount_pln: Decimal
    note: str | None


# ------------------------------------------------------ identity / staff portal (F6)
class InviteCreate(BaseModel):
    """Exactly one target: an employee (staff invite) or a client (F7 invite)."""

    employee_id: int | None = None
    client_id: int | None = None
    expires_in_days: int = Field(default=14, ge=1, le=90)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "InviteCreate":
        if (self.employee_id is None) == (self.client_id is None):
            raise ValueError("give exactly one of employee_id / client_id")
        return self


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    role: str
    employee_id: int | None
    client_id: int | None
    expires_at: datetime | None
    claimed_at: datetime | None
    claimed_by_sub: str | None


class InviteClaim(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class MeLink(BaseModel):
    """Who the current login is, for the staff portal. `linked` is false until an
    invite is claimed — the front end then shows the claim box."""

    linked: bool
    role: str
    employee_id: int | None = None
    display_name: str | None = None
    fte_factor: Decimal | None = None
    pay_type: PayType | None = None
    is_active: bool | None = None


class MeRevenueOut(BaseModel):
    year_month: str
    booksy_services: Decimal
    cash_services: Decimal
    notebook_services: Decimal
    services_total: Decimal


class MeCommissionOut(BaseModel):
    """A read-only live preview of the caller's own commission for the month,
    computed from the daily sources with their current scheme. Not a settlement
    line — the owner still closes the period; this just lets staff see it early."""

    year_month: str
    services_base: Decimal
    services_rate: Decimal
    services_commission: Decimal
    sales_commission: Decimal
    hours: Decimal
    hours_pay: Decimal
    total_payout: Decimal


class MeTimesheetCreate(BaseModel):
    """Staff self-entry of own hours — employee_id comes from the token, never
    the body (row-scoping: you can only log your own)."""

    work_date: date
    hours: Decimal = Field(ge=0, le=MAX_HOURS_PER_DAY, max_digits=5, decimal_places=2)
    note: str | None = None


class MeCashCreate(BaseModel):
    entry_date: date
    service_name: str = Field(min_length=1, max_length=200)
    amount_pln: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    note: str | None = None


class MeNotebookCreate(BaseModel):
    """Staff self-entry of a prepaid (package/voucher) visit performed — credits
    commission to the caller. employee_id comes from the token, never the body."""

    entry_date: date
    service_name: str = Field(min_length=1, max_length=200)
    amount_pln: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    note: str | None = None


# ------------------------------------------------------- supplies list (Day 1)
class SupplyItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    note: str | None = None


class SupplyItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = Field(default=None, pattern=r"^(to_buy|bought)$")
    note: str | None = None


class SupplyItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    note: str | None
    created_by: str | None
    bought_at: datetime | None


# ------------------------------------------------- staff documents (Day 1)
class StaffDocumentCreate(BaseModel):
    employee_id: int
    doc_type: str = Field(default="umowa", pattern=r"^(umowa|rodo|inne)$")
    title: str | None = Field(default=None, max_length=200)
    valid_until: date | None = None
    note: str | None = None


class StaffDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    doc_type: str
    title: str | None
    valid_until: date | None
    note: str | None


# ----------------------------------------- availability + time off (Day 1)
class AvailabilityCreate(BaseModel):
    """Staff declares a day they can work. employee_id is from the token."""

    work_date: date
    from_time: time | None = None
    to_time: time | None = None
    note: str | None = None


class AvailabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    work_date: date
    from_time: time | None
    to_time: time | None
    note: str | None


class TimeOffCreate(BaseModel):
    start_date: date
    end_date: date
    kind: str = Field(default="urlop", pattern=r"^(urlop|inne)$")
    note: str | None = None


class TimeOffUpdate(BaseModel):
    status: str = Field(pattern=r"^(requested|approved)$")


class TimeOffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    start_date: date
    end_date: date
    kind: str
    status: str
    note: str | None


# ------------------------------------------- daily cash reconciliation (Day 2)
class SalonDayIn(BaseModel):
    """What a person types for a day's till: cash taken via Booksy and the
    fiscal-register (POS) total. Unregistered cash is derived, never typed."""

    booksy_cash: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    fiscal_register: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    note: str | None = None


class SalonDayOut(BaseModel):
    day: date
    booksy_cash: Decimal
    fiscal_register: Decimal
    # Derived from the day's ledger entries (all employees), never stored:
    unregistered_cash: Decimal  # "gotówka nie wbita"
    cash_in_register: Decimal  # unregistered + booksy_cash ("suma gotówki w kasie")
    note: str | None


class PackageOut(BaseModel):
    id: int
    client_name: str
    name: str
    total_value: Decimal
    total_treatments: int
    remaining: int
    used: int
    value_per_treatment: Decimal  # total_value / total_treatments (prowizja za realizację)
    valid_until: date | None
    status: str  # active | used_up | expired
    manual_used: int = 0  # manual redemptions on top of Booksy's count
    effective_remaining: int = 0  # Booksy remaining − manual_used


class MonthlyKasaOut(BaseModel):
    """A month's till reconciliation (salon-wide). All summed/derived, nothing
    stored twice."""

    year_month: str
    fiscal_register: Decimal  # Σ kasa fiskalna (gotówka + karta)
    booksy_cash: Decimal  # Σ gotówka z Booksy
    card: Decimal  # fiscal_register − booksy_cash (płatności kartą/terminal)
    unregistered_cash: Decimal  # Σ gotówka nie wbita (z ewidencji)
    cash_total: Decimal  # booksy_cash + unregistered ("prawdziwa suma gotówki")
    money_total: Decimal  # fiscal_register + unregistered ("prawdziwa suma pieniędzy")


# --- Expenses & P&L (F12) ---
_YM = r"^\d{4}-(0[1-9]|1[0-2])$"


class ExpenseLineIn(BaseModel):
    """A cost line the owner enters for a month (a 'subcategory' = the name)."""

    year_month: str = Field(pattern=_YM)
    category_code: str
    name: str = Field(min_length=1, max_length=120)
    amount_pln: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    vendor: str | None = Field(default=None, max_length=120)
    incurred_on: date | None = None
    note: str | None = None


class ExpenseLineUpdate(BaseModel):
    category_code: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    amount_pln: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    vendor: str | None = Field(default=None, max_length=120)
    incurred_on: date | None = None
    note: str | None = None


class ExpenseLineOut(BaseModel):
    id: int
    category_code: str
    name: str
    amount_pln: Decimal
    vendor: str | None
    source: str  # manual | recurring | statement
    incurred_on: date | None
    note: str | None


class RecurringIn(BaseModel):
    category_code: str
    name: str = Field(min_length=1, max_length=120)
    amount_pln: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    active: bool = True


class RecurringUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    amount_pln: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    active: bool | None = None


class RecurringOut(BaseModel):
    id: int
    category_code: str
    name: str
    amount_pln: Decimal
    active: bool


class PnlCategoryOut(BaseModel):
    code: str
    name: str
    total: Decimal
    lines: list[ExpenseLineOut]


class PnlOut(BaseModel):
    """A month's full P&L, mirroring the owner's sheet layout."""

    year_month: str
    status: str  # draft | closed
    revenue: Decimal  # UTARG
    revenue_source: str  # computed | override | snapshot
    categories: list[PnlCategoryOut]  # the 6 operating categories, with lines
    operating_total: Decimal  # KOSZTY ŁĄCZNE
    staff_cost: Decimal  # KOSZT PRACOWNICY
    staff_cost_source: str  # settlement | override | snapshot | none
    costs_total: Decimal  # PODSUMOWANIE KOSZTÓW
    profit: Decimal  # ZAROBEK
    note: str | None
    closed_at: datetime | None


class PnlMonthSummary(BaseModel):
    year_month: str
    status: str
    revenue: Decimal
    costs_total: Decimal
    profit: Decimal


class PnlOverrideIn(BaseModel):
    """Admin overrides for a draft month (null clears an override)."""

    revenue_override: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    staff_cost_override: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    note: str | None = None
    clear_revenue_override: bool = False
    clear_staff_cost_override: bool = False


# --- Bank statement import (MT940 → expenses) ---
class StatementTxnOut(BaseModel):
    id: int
    value_date: date
    amount: Decimal
    counterparty: str
    title: str
    category: str | None  # assigned category code (null = needs a human)
    name: str
    bucket: str  # operating | staff | owner_draw | unknown
    status: str  # pending | imported | ignored


class StatementImportSummary(BaseModel):
    year_month: str  # dominant month in the file
    parsed: int  # debits found
    added: int  # new pending/ignored rows
    duplicates: int  # bank_refs already seen, skipped
    needs_review: int  # added rows with no suggested category


class StatementTxnUpdate(BaseModel):
    category: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: str | None = None  # pending | ignored
    clear_category: bool = False


class StatementMaterializeSummary(BaseModel):
    year_month: str
    expenses_created: int
    txns_imported: int
    unassigned: int  # pending, no category → skipped (assign or ignore first)
    recurring_cleared: int  # template lines removed in favor of bank actuals


# --- Vouchers (gift cards) ---
class VoucherRedemptionOut(BaseModel):
    id: int
    amount: Decimal
    redeemed_on: date
    note: str | None
    created_by: str | None  # audit: who
    created_at: datetime  # audit: when


class VoucherOut(BaseModel):
    id: int
    client_name: str
    description: str
    total_value: Decimal
    remaining_value: Decimal
    purchased_on: date | None
    valid_until: date | None
    status: str  # active | used | expired
    note: str | None
    source: str
    redemptions: list[VoucherRedemptionOut]


class VoucherCreate(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=300)
    total_value: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    remaining_value: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    purchased_on: date | None = None
    valid_until: date | None = None
    note: str | None = None


class VoucherUpdate(BaseModel):
    client_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=300)
    total_value: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    remaining_value: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    valid_until: date | None = None
    note: str | None = None


class VoucherRedeemIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    redeemed_on: date | None = None
    note: str | None = None


class VoucherImportSummary(BaseModel):
    parsed: int  # rows with a parseable value
    imported: int  # active ones added
    skipped_existing: int
    skipped_inactive: int  # parsed but expired/old → not imported


# --- Package redemptions: manual marking + performer assignment ---
class PackageRedeemIn(BaseModel):
    """Mark a package treatment used manually (Booksy missed it — e.g. a late
    cancel). Optional performer → credits commission; omit for a pure count fix."""

    employee_id: int | None = None
    redemption_date: date | None = None
    note: str | None = None


class RedemptionAssignIn(BaseModel):
    employee_id: int | None = None
    package_id: int | None = None
    note: str | None = None
    clear_employee: bool = False


class RedemptionOut(BaseModel):
    id: int
    package_id: int | None
    package_name: str | None
    client_name: str
    redemption_date: date
    value: Decimal
    employee_id: int | None
    employee_name: str | None
    source: str  # booksy | manual
    note: str | None
    created_by: str | None  # audit: who marked a manual one
    assigned_by: str | None  # audit: who set the performer
    created_at: datetime


# --- Client portal (F7) ---
class ClientMeOut(BaseModel):
    """The client login's link state + a light profile. Never exposes
    Client.notes (owner rule: the note is staff/admin-only)."""

    linked: bool
    client_id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    total_visits: int = 0
    first_visit: datetime | None = None
    last_visit: datetime | None = None


class ClientPackageOut(BaseModel):
    name: str
    total_treatments: int
    remaining: int  # effective (Booksy − manual marks)
    valid_until: date | None
    status: str  # active | used_up | expired


class ClientVoucherOut(BaseModel):
    description: str
    total_value: Decimal
    remaining_value: Decimal
    valid_until: date | None
    status: str  # active | used | expired


# --- Staff cost + salon break-even (wydatki page) ---
class StaffCostRow(BaseModel):
    employee_id: int
    name: str
    pay_type: str  # hourly | uop_plus_extra
    hours: Decimal
    revenue: Decimal  # utarg usług miesiąca (aktualny)
    base_cost: Decimal  # godziny×stawka, lub pensja + nadgodziny (UoP)
    commission: Decimal  # prowizja aktualna
    total_cost: Decimal  # base_cost + commission
    breakeven_revenue: Decimal  # utarg, przy którym salon pokrywa jej koszt
    over_under: Decimal  # revenue − total_cost (>0 = salon na plusie)
    needs_base: bool  # UoP bez ustawionej pensji → poproś o wpisanie


class StaffCostOut(BaseModel):
    year_month: str
    rows: list[StaffCostRow]
    total_cost: Decimal  # Σ total_cost = KOSZT PRACOWNICY


# --- Service catalog + rebooking (F8) ---
class ServiceOut(BaseModel):
    id: int
    name: str
    visit_count: int  # completed visits — helps the owner curate the top ones
    rebook_interval_days: int | None
    recommendation: str | None
    active: bool


class ServiceUpdate(BaseModel):
    rebook_interval_days: int | None = Field(default=None, ge=1, le=1095)
    recommendation: str | None = None
    active: bool | None = None
    clear_interval: bool = False


class CatalogSyncSummary(BaseModel):
    total: int  # services in the catalog after sync
    created: int  # new names added from visits


class RebookingSuggestion(BaseModel):
    service: str
    last_visit: date
    interval_days: int
    suggested_next: date
    due: bool  # suggested_next <= today
    recommendation: str | None


class DueRebook(BaseModel):
    client_id: int
    client_name: str
    phone: str | None
    service: str
    last_visit: date
    suggested_next: date
