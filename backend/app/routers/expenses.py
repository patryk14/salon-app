"""Expenses & monthly P&L (F12) — admin-only finance.

Reproduces the owner's monthly cost sheet. Revenue (kasa) and staff cost
(settlement payouts) are DERIVED; only operating costs are entered here, grouped
into her categories. A month is 'opened' on first view — its fixed recurring
lines are materialized once, then freely edited. Closing freezes the derived
inputs and locks the month, exactly like a settlement period.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import UserDep, require_role
from app.deps import get_db
from app.models import Expense, ExpenseCategory, PnlMonth, RecurringExpense
from app.pnl import ensure_categories, month_money_total, month_staff_cost, totals
from app.schemas import (
    ExpenseLineIn,
    ExpenseLineOut,
    ExpenseLineUpdate,
    PnlCategoryOut,
    PnlMonthSummary,
    PnlOut,
    PnlOverrideIn,
    RecurringIn,
    RecurringOut,
    RecurringUpdate,
    StaffCostOut,
    StaffCostRow,
)

DbDep = Annotated[Session, Depends(get_db)]
YM = Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def _ensure_categories(db: DbDep) -> None:
    """Router dependency: cost categories (reference data) always exist."""
    ensure_categories(db)


_ADMIN = [require_role("admin"), Depends(_ensure_categories)]
pnl = APIRouter(prefix="/pnl", tags=["pnl"], dependencies=_ADMIN)
expenses = APIRouter(prefix="/expenses", tags=["expenses"], dependencies=_ADMIN)


# --- helpers ---------------------------------------------------------------
def _cat_by_code(db: Session, code: str) -> ExpenseCategory:
    cat = db.scalar(select(ExpenseCategory).where(ExpenseCategory.code == code))
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Nie ma kategorii '{code}'.")
    return cat


def _line_out(e: Expense, code: str) -> ExpenseLineOut:
    return ExpenseLineOut(
        id=e.id,
        category_code=code,
        name=e.name,
        amount_pln=e.amount_pln,
        vendor=e.vendor,
        source=e.source,
        incurred_on=e.incurred_on,
        note=e.note,
    )


def _prefill(db: Session, year_month: str, username: str | None) -> None:
    """Materialize active recurring templates into the month, once (at open)."""
    for rec in db.scalars(select(RecurringExpense).where(RecurringExpense.active.is_(True))).all():
        db.add(
            Expense(
                year_month=year_month,
                category_id=rec.category_id,
                name=rec.name,
                amount_pln=rec.amount_pln,
                source="recurring",
                created_by=username,
            )
        )
    db.flush()


def _open_month(db: Session, year_month: str, username: str | None) -> PnlMonth:
    """Get the month, or open it: create a draft and prefill recurring lines once."""
    row = db.scalar(select(PnlMonth).where(PnlMonth.year_month == year_month))
    if row is None:
        row = PnlMonth(year_month=year_month, status="draft")
        db.add(row)
        db.flush()
        _prefill(db, year_month, username)
    return row


def _month_row(db: Session, year_month: str) -> PnlMonth:
    """Get the month row (create a bare draft if missing) — no prefill; for
    mutations on a month that already holds lines."""
    row = db.scalar(select(PnlMonth).where(PnlMonth.year_month == year_month))
    if row is None:
        row = PnlMonth(year_month=year_month, status="draft")
        db.add(row)
        db.flush()
    return row


def _guard_open(row: PnlMonth) -> None:
    if row.status == "closed":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Miesiąc zamknięty — otwórz ponownie, aby edytować."
        )


def _build_pnl(db: Session, year_month: str, row: PnlMonth) -> PnlOut:
    cats = db.scalars(select(ExpenseCategory).order_by(ExpenseCategory.display_order)).all()
    code_by_id = {c.id: c.code for c in cats}
    cat_totals: dict[str, Decimal] = {c.code: Decimal("0") for c in cats}
    lines_by_code: dict[str, list[ExpenseLineOut]] = {c.code: [] for c in cats}
    for e in db.scalars(
        select(Expense).where(Expense.year_month == year_month).order_by(Expense.id)
    ).all():
        code = code_by_id.get(e.category_id)
        if code is None:
            continue
        cat_totals[code] += e.amount_pln
        lines_by_code[code].append(_line_out(e, code))

    closed = row.status == "closed"
    if closed:
        revenue, revenue_source = row.revenue_snapshot or Decimal("0"), "snapshot"
    elif row.revenue_override is not None:
        revenue, revenue_source = row.revenue_override, "override"
    else:
        revenue, revenue_source = month_money_total(db, year_month), "computed"

    if closed:
        staff, staff_source = row.staff_cost_snapshot or Decimal("0"), "snapshot"
    elif row.staff_cost_override is not None:
        staff, staff_source = row.staff_cost_override, "override"
    else:
        derived = month_staff_cost(db, year_month)
        if derived is not None and derived > 0:  # a real settlement is entered → authoritative
            staff, staff_source = derived, "settlement"
        else:  # no settlement yet → live estimate (statutory hours + commission)
            _, staff = _staff_rows(db, year_month)
            staff_source = "estimate"

    t = totals(revenue, cat_totals, staff)
    return PnlOut(
        year_month=year_month,
        status=row.status,
        revenue=t.revenue,
        revenue_source=revenue_source,
        categories=[
            PnlCategoryOut(
                code=c.code, name=c.name, total=cat_totals[c.code], lines=lines_by_code[c.code]
            )
            for c in cats
        ],
        operating_total=t.operating_total,
        staff_cost=t.staff_cost,
        staff_cost_source=staff_source,
        costs_total=t.costs_total,
        profit=t.profit,
        note=row.note,
        closed_at=row.closed_at,
    )


# --- P&L -------------------------------------------------------------------
@pnl.get("")
def list_months(db: DbDep) -> list[PnlMonthSummary]:
    """Every opened month, newest first (read-only)."""
    out: list[PnlMonthSummary] = []
    for row in db.scalars(select(PnlMonth).order_by(PnlMonth.year_month.desc())).all():
        p = _build_pnl(db, row.year_month, row)
        out.append(
            PnlMonthSummary(
                year_month=p.year_month,
                status=p.status,
                revenue=p.revenue,
                costs_total=p.costs_total,
                profit=p.profit,
            )
        )
    return out


@pnl.get("/{year_month}")
def get_month(year_month: YM, user: UserDep, db: DbDep) -> PnlOut:
    """The month's full P&L. Opens the month (prefills fixed costs) on first view."""
    return _build_pnl(db, year_month, _open_month(db, year_month, user.username))


@pnl.put("/{year_month}")
def set_overrides(year_month: YM, payload: PnlOverrideIn, user: UserDep, db: DbDep) -> PnlOut:
    row = _open_month(db, year_month, user.username)
    _guard_open(row)
    if payload.clear_revenue_override:
        row.revenue_override = None
    elif payload.revenue_override is not None:
        row.revenue_override = payload.revenue_override
    if payload.clear_staff_cost_override:
        row.staff_cost_override = None
    elif payload.staff_cost_override is not None:
        row.staff_cost_override = payload.staff_cost_override
    if payload.note is not None:
        row.note = payload.note
    db.flush()
    return _build_pnl(db, year_month, row)


@pnl.post("/{year_month}/close")
def close_month(year_month: YM, user: UserDep, db: DbDep) -> PnlOut:
    """Freeze the derived revenue + staff cost and lock the month's costs."""
    row = _open_month(db, year_month, user.username)
    if row.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Miesiąc już zamknięty.")
    live = _build_pnl(db, year_month, row)  # computed revenue + staff before freezing
    row.revenue_snapshot = live.revenue
    row.staff_cost_snapshot = live.staff_cost
    row.status = "closed"
    row.closed_at = datetime.now(UTC)
    row.closed_by = user.username
    db.flush()
    return _build_pnl(db, year_month, row)


def _staff_rows(db: Session, year_month: str) -> tuple[list[StaffCostRow], Decimal]:
    """Per-employee cost + break-even for the month (live). Base = statutory month
    hours × FTE × rate for zlecenie (or logged if higher), or a UoP fixed salary;
    plus commission. Shared by the /staff view and the P&L staff-cost estimate."""
    from app.commission import SettlementInput, breakeven_revenue, compute_settlement
    from app.derivation import (
        monthly_booksy_services,
        monthly_cash,
        monthly_hours,
        monthly_notebook_services,
    )
    from app.models import Employee
    from app.pnl import standard_monthly_hours
    from app.routers.settlement import _scheme_for

    std_hours = Decimal(standard_monthly_hours(year_month))  # full-time Mon–Fri × 8
    rows: list[StaffCostRow] = []
    total = Decimal("0")
    employees = db.scalars(
        select(Employee).where(Employee.active_to.is_(None)).order_by(Employee.display_name)
    ).all()
    for e in employees:
        scheme = _scheme_for(e)
        revenue = (
            monthly_booksy_services(db, e.id, year_month)
            + monthly_cash(db, e.id, year_month)
            + monthly_notebook_services(db, e.id, year_month)
        )
        logged = monthly_hours(db, e.id, year_month)
        # commission is independent of hours (services + sales only)
        result = compute_settlement(SettlementInput(booksy_services=revenue), scheme)
        commission = result.services_commission + result.sales_commission
        if e.pay_type == "uop_plus_extra":  # Klaudia: fixed salary + any extra logged hours
            hours = logged
            base_cost = (e.monthly_base_pln or Decimal("0")) + logged * e.hourly_rate
            needs_base = e.monthly_base_pln is None
        else:  # zlecenie: statutory month hours × FTE (the salary they're paid), or more if logged
            hours = max(logged, std_hours * e.fte_factor)
            base_cost = (hours * e.hourly_rate).quantize(Decimal("0.01"))
            needs_base = False
        total_cost = base_cost + commission
        rows.append(
            StaffCostRow(
                employee_id=e.id,
                name=e.display_name,
                pay_type=e.pay_type,
                hours=hours,
                revenue=revenue,
                base_cost=base_cost,
                commission=commission,
                total_cost=total_cost,
                breakeven_revenue=breakeven_revenue(base_cost, scheme),
                over_under=revenue - total_cost,
                needs_base=needs_base,
            )
        )
        total += total_cost
    return rows, total


@pnl.get("/{year_month}/staff")
def staff_cost(year_month: YM, db: DbDep) -> StaffCostOut:
    """Per-employee cost + salon break-even for the month (live, from daily sources)."""
    rows, total = _staff_rows(db, year_month)
    return StaffCostOut(year_month=year_month, rows=rows, total_cost=total)


@pnl.post("/{year_month}/reopen")
def reopen_month(year_month: YM, db: DbDep) -> PnlOut:
    row = db.scalar(select(PnlMonth).where(PnlMonth.year_month == year_month))
    if row is None or row.status != "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Miesiąc nie jest zamknięty.")
    row.status = "draft"
    row.revenue_snapshot = None
    row.staff_cost_snapshot = None
    row.closed_at = None
    row.closed_by = None
    db.flush()
    return _build_pnl(db, year_month, row)


# --- expense lines ---------------------------------------------------------
@expenses.get("/categories")
def list_categories(db: DbDep) -> list[dict[str, str]]:
    cats = db.scalars(select(ExpenseCategory).order_by(ExpenseCategory.display_order)).all()
    return [{"code": c.code, "name": c.name} for c in cats]


@expenses.post("")
def add_line(payload: ExpenseLineIn, user: UserDep, db: DbDep) -> PnlOut:
    row = _open_month(db, payload.year_month, user.username)
    _guard_open(row)
    cat = _cat_by_code(db, payload.category_code)
    db.add(
        Expense(
            year_month=payload.year_month,
            category_id=cat.id,
            name=payload.name.strip(),
            amount_pln=payload.amount_pln,
            vendor=payload.vendor,
            incurred_on=payload.incurred_on,
            note=payload.note,
            source="manual",
            created_by=user.username,
        )
    )
    db.flush()
    return _build_pnl(db, payload.year_month, row)


@expenses.put("/{expense_id}")
def update_line(expense_id: int, payload: ExpenseLineUpdate, db: DbDep) -> PnlOut:
    e = db.get(Expense, expense_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej pozycji.")
    row = _month_row(db, e.year_month)
    _guard_open(row)
    if payload.category_code is not None:
        e.category_id = _cat_by_code(db, payload.category_code).id
    if payload.name is not None:
        e.name = payload.name.strip()
    if payload.amount_pln is not None:
        e.amount_pln = payload.amount_pln
    if payload.vendor is not None:
        e.vendor = payload.vendor
    if payload.incurred_on is not None:
        e.incurred_on = payload.incurred_on
    if payload.note is not None:
        e.note = payload.note
    db.flush()
    return _build_pnl(db, e.year_month, row)


@expenses.delete("/{expense_id}")
def delete_line(expense_id: int, db: DbDep) -> PnlOut:
    e = db.get(Expense, expense_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej pozycji.")
    row = _month_row(db, e.year_month)
    _guard_open(row)
    year_month = e.year_month
    db.delete(e)
    db.flush()
    return _build_pnl(db, year_month, row)


# --- recurring templates ---------------------------------------------------
def _rec_out(rec: RecurringExpense, code: str) -> RecurringOut:
    return RecurringOut(
        id=rec.id, category_code=code, name=rec.name, amount_pln=rec.amount_pln, active=rec.active
    )


@expenses.get("/recurring")
def list_recurring(db: DbDep) -> list[RecurringOut]:
    codes = {c.id: c.code for c in db.scalars(select(ExpenseCategory)).all()}
    return [
        _rec_out(r, codes.get(r.category_id, ""))
        for r in db.scalars(select(RecurringExpense).order_by(RecurringExpense.id)).all()
    ]


@expenses.post("/recurring")
def add_recurring(payload: RecurringIn, db: DbDep) -> RecurringOut:
    cat = _cat_by_code(db, payload.category_code)
    rec = RecurringExpense(
        category_id=cat.id,
        name=payload.name.strip(),
        amount_pln=payload.amount_pln,
        active=payload.active,
    )
    db.add(rec)
    db.flush()
    return _rec_out(rec, cat.code)


@expenses.put("/recurring/{rec_id}")
def update_recurring(rec_id: int, payload: RecurringUpdate, db: DbDep) -> RecurringOut:
    rec = db.get(RecurringExpense, rec_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego szablonu.")
    if payload.name is not None:
        rec.name = payload.name.strip()
    if payload.amount_pln is not None:
        rec.amount_pln = payload.amount_pln
    if payload.active is not None:
        rec.active = payload.active
    db.flush()
    cat = db.get(ExpenseCategory, rec.category_id)
    return _rec_out(rec, cat.code if cat else "")


@expenses.delete("/recurring/{rec_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring(rec_id: int, db: DbDep) -> None:
    rec = db.get(RecurringExpense, rec_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego szablonu.")
    db.delete(rec)
    db.flush()
