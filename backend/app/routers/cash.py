"""Daily cash reconciliation (Day 2) — the salon-wide till, per day.

Admin-only. 'Gotówka nie wbita' (unregistered cash) is always summed from the
day's ledger entries here, never stored, so it stays consistent with the daily
report. The row only persists what a person types: Booksy cash and the fiscal
register total. 'Suma gotówki w kasie' = unregistered + Booksy.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import UserDep, require_role
from app.deps import get_db
from app.derivation import month_bounds
from app.models import LedgerEntry, SalonDay
from app.reconciliation import (
    Txn,
    day_txns,
    find_candidates,
    month_days,
    status_of,
    txn_count,
)
from app.schemas import (
    DayReconciliationOut,
    MonthlyKasaOut,
    MonthReconDayOut,
    ReconTxnOut,
    SalonDayIn,
    SalonDayOut,
)

DbDep = Annotated[Session, Depends(get_db)]
MonthQuery = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]

# Staff too: closing the till ('rozliczenie dnia') is front-desk work. The
# owner isn't always in the salon. SalonDayOut exposes only day totals, never a
# per-employee breakdown, so no one's individual numbers leak.
salon_days = APIRouter(prefix="/salon-days", tags=["cash"], dependencies=[require_role("staff")])


@salon_days.get("/summary")
def salon_month_summary(db: DbDep, month: MonthQuery) -> MonthlyKasaOut:
    """A month's till reconciliation (salon-wide). Registered BEFORE /{day} so
    the literal 'summary' isn't parsed as a date."""
    start, end = month_bounds(month)

    def total(col, *where) -> Decimal:
        return Decimal(str(db.scalar(select(func.coalesce(func.sum(col), 0)).where(*where))))

    fiscal = total(SalonDay.fiscal_register, SalonDay.day >= start, SalonDay.day < end)
    booksy = total(SalonDay.booksy_cash, SalonDay.day >= start, SalonDay.day < end)
    unreg = total(
        LedgerEntry.amount_pln, LedgerEntry.entry_date >= start, LedgerEntry.entry_date < end
    )
    return MonthlyKasaOut(
        year_month=month,
        fiscal_register=fiscal,
        booksy_cash=booksy,
        card=fiscal - booksy,
        unregistered_cash=unreg,
        cash_total=booksy + unreg,
        money_total=fiscal + unreg,
    )


def _gap(row: SalonDay | None) -> Decimal | None:
    if row is None or row.fiscal_printer_total is None:
        return None
    return row.fiscal_register - row.fiscal_printer_total


@salon_days.get("/reconciliation")
def month_reconciliation(db: DbDep, month: MonthQuery) -> list[MonthReconDayOut]:
    """Every day of the month that has a till: Booksy vs the fiscal printer.
    Registered BEFORE /{day} (a literal path must not be parsed as a date)."""
    start, end = month_bounds(month)
    return [
        MonthReconDayOut(
            day=r.day,
            status=status_of(r.fiscal_printer_total, _gap(r), r.recon_explained),
            booksy_till=r.fiscal_register,
            fiscal_printer_total=r.fiscal_printer_total,
            gap=_gap(r),
        )
        for r in month_days(db, start, end)
    ]


def _txn_out(t: Txn) -> ReconTxnOut:
    return ReconTxnOut(
        doc=t.doc,
        client=t.client,
        performer=t.performer,
        cashier=t.cashier,
        method=t.method,
        amount=t.amount,
    )


@salon_days.get("/{day}/reconciliation")
def day_reconciliation(day: date, user: UserDep, db: DbDep) -> DayReconciliationOut:
    """Booksy's till vs the fiscal printer for one day. A positive gap means
    something was settled in Booksy but never rung up — the candidates are the
    Booksy transactions whose amount equals that gap, with the performer.

    Everyone at the desk sees THAT the day doesn't add up; only an admin sees the
    transactions and who performed them — this page is shared by the whole team
    and a candidate list points at a colleague."""
    row = db.scalar(select(SalonDay).where(SalonDay.day == day))
    gap = _gap(row)
    txns = day_txns(db, day) if "admin" in user.groups else []
    return DayReconciliationOut(
        day=day,
        status=status_of(
            row.fiscal_printer_total if row else None, gap, row.recon_explained if row else False
        ),
        booksy_till=row.fiscal_register if row else Decimal("0"),
        fiscal_printer_total=row.fiscal_printer_total if row else None,
        gap=gap,
        note=row.note if row else None,
        synced=txn_count(db, day) > 0,
        candidates=[
            [_txn_out(t) for t in group] for group in find_candidates(txns, gap or Decimal(0))
        ],
        transactions=[_txn_out(t) for t in txns],
    )


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
        fiscal_printer_total=row.fiscal_printer_total if row else None,
        recon_explained=row.recon_explained if row else False,
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
    sent = payload.model_fields_set
    if "fiscal_printer_total" in sent:
        row.fiscal_printer_total = payload.fiscal_printer_total
    if "recon_explained" in sent and payload.recon_explained is not None:
        row.recon_explained = payload.recon_explained
    db.flush()
    return _out(day, row, _unregistered(db, day))
