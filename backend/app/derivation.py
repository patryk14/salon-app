"""Deriving a month's settlement inputs from the daily sources — so the monthly
panel is ASSEMBLED, never typed. Three sources per employee per month:

  hours           ← timesheet_entries (F3)
  cash_services   ← ledger_entries (F3)   (unregistered cash, 'Gotówka')
  booksy_services ← imported visits (F5)  (completed visits, resolved by alias)

booksy_sales (products) and notebook packages are not derived here yet — product
imports (F5) and the notebook (F4) come later; until then they stay manual.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EmployeeAlias, LedgerEntry, TimesheetEntry, Visit


def month_bounds(year_month: str) -> tuple[date, date]:
    """[start, end) — half-open, avoids month-length / leap-year edge cases."""
    year, month = (int(p) for p in year_month.split("-"))
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def monthly_hours(db: Session, employee_id: int, year_month: str) -> Decimal:
    start, end = month_bounds(year_month)
    total = db.scalar(
        select(func.coalesce(func.sum(TimesheetEntry.hours), 0)).where(
            TimesheetEntry.employee_id == employee_id,
            TimesheetEntry.work_date >= start,
            TimesheetEntry.work_date < end,
        )
    )
    return Decimal(str(total))


def monthly_cash(db: Session, employee_id: int, year_month: str) -> Decimal:
    start, end = month_bounds(year_month)
    total = db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount_pln), 0)).where(
            LedgerEntry.employee_id == employee_id,
            LedgerEntry.entry_date >= start,
            LedgerEntry.entry_date < end,
        )
    )
    return Decimal(str(total))


def monthly_booksy_services(db: Session, employee_id: int, year_month: str) -> Decimal:
    """Sum of COMPLETED visits for the month, credited to the employee via their
    Booksy-name aliases. Cancelled / no-show visits earn nothing. Booksy exports
    carry a free-text 'Pracownik' (stored as visit.staff_name) — the alias table
    is what maps 'Karolina' → Karola, 'Hanna' → Hania.
    """
    start, end = month_bounds(year_month)
    aliases = select(EmployeeAlias.alias).where(EmployeeAlias.employee_id == employee_id)
    total = db.scalar(
        select(func.coalesce(func.sum(Visit.price_pln), 0)).where(
            Visit.staff_name.in_(aliases),
            Visit.status == "completed",
            Visit.starts_at >= start,
            Visit.starts_at < end,
        )
    )
    return Decimal(str(total))


def unmatched_staff_names(db: Session, year_month: str) -> list[str]:
    """Booksy staff names in the month that no alias resolves — a loud signal
    that revenue is being dropped (a new or renamed employee). Safeguard input."""
    start, end = month_bounds(year_month)
    known = select(EmployeeAlias.alias)
    rows = db.scalars(
        select(Visit.staff_name)
        .where(
            Visit.staff_name.is_not(None),
            Visit.staff_name.not_in(known),
            Visit.starts_at >= start,
            Visit.starts_at < end,
        )
        .distinct()
    ).all()
    return list(rows)
