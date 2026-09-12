"""Daily cash reconciliation (Day 2) — the salon-wide till, per day.

Admin-only. 'Gotówka nie wbita' (unregistered cash) is always summed from the
day's ledger entries here, never stored, so it stays consistent with the daily
report. The row only persists what a person types: Booksy cash and the fiscal
register total. 'Suma gotówki w kasie' = unregistered + Booksy.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.deps import get_db
from app.models import LedgerEntry, SalonDay
from app.schemas import SalonDayIn, SalonDayOut

DbDep = Annotated[Session, Depends(get_db)]

salon_days = APIRouter(prefix="/salon-days", tags=["cash"], dependencies=[require_role("admin")])


def _unregistered(db: Session, day: date) -> Decimal:
    """Sum of the day's ledger cash (all employees) — the 'gotówka nie wbita'."""
    total = db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount_pln), 0)).where(
            LedgerEntry.entry_date == day
        )
    )
    return Decimal(str(total))


def _out(day: date, row: SalonDay | None, unregistered: Decimal) -> SalonDayOut:
    booksy = row.booksy_cash if row else Decimal("0")
    fiscal = row.fiscal_register if row else Decimal("0")
    return SalonDayOut(
        day=day,
        booksy_cash=booksy,
        fiscal_register=fiscal,
        unregistered_cash=unregistered,
        cash_in_register=unregistered + booksy,
        note=row.note if row else None,
    )


@salon_days.get("/{day}")
def get_salon_day(day: date, db: DbDep) -> SalonDayOut:
    """Reconciliation for a day. Works before anything is typed: unregistered
    cash is derived from the ledger, the rest defaults to 0."""
    row = db.scalar(select(SalonDay).where(SalonDay.day == day))
    return _out(day, row, _unregistered(db, day))


@salon_days.put("/{day}")
def upsert_salon_day(day: date, payload: SalonDayIn, db: DbDep) -> SalonDayOut:
    row = db.scalar(select(SalonDay).where(SalonDay.day == day))
    if row is None:
        row = SalonDay(day=day)
        db.add(row)
    row.booksy_cash = payload.booksy_cash
    row.fiscal_register = payload.fiscal_register
    row.note = payload.note
    db.flush()
    return _out(day, row, _unregistered(db, day))
