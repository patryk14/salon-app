"""Daily cash reconciliation (Day 2) — the salon-wide till, per day.

Admin-only. 'Gotówka nie wbita' (unregistered cash) is always summed from the
day's ledger entries here, never stored, so it stays consistent with the daily
report. The row only persists what a person types: Booksy cash and the fiscal
register total. 'Suma gotówki w kasie' = unregistered + Booksy.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import UserDep, require_role
from app.deps import get_db
from app.derivation import month_bounds
from app.models import LedgerEntry, SalonDay
from app.pnl import month_shop_sales
from app.reconciliation import (
    Txn,
    booksy_till_by_day,
    day_txns,
    find_candidates,
    month_days,
    shop_fiscal_by_day,
    status_of,
)
from app.schemas import (
    DayReconciliationOut,
    MonthlyKasaOut,
    MonthReconDayOut,
    ReconExplainIn,
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
    shop = month_shop_sales(db, month)
    return MonthlyKasaOut(
        year_month=month,
        fiscal_register=fiscal,
        booksy_cash=booksy,
        card=fiscal - booksy,
        unregistered_cash=unreg,
        cash_total=booksy + unreg,
        shop_sales=shop,
        money_total=fiscal + unreg + shop,
    )


ZERO = Decimal("0")


@dataclass(frozen=True)
class _DayFigures:
    """One day's reconciliation inputs. `till` comes from the KEPT Booksy
    transactions when we have them (has_till / synced); the hand-editable
    salon_days.fiscal_register is only a fallback for days never synced."""

    till: Decimal
    shop: Decimal
    printer: Decimal | None
    has_till: bool
    explained_gap: Decimal | None

    @property
    def gap(self) -> Decimal | None:
        """expected − printed, where expected = Booksy's till + the app's shop sales."""
        return None if self.printer is None else self.till + self.shop - self.printer

    @property
    def status(self) -> str:
        return status_of(self.printer, self.gap, self.explained_gap, self.has_till)


def _figures(row: SalonDay | None, synced_till: Decimal | None, shop: Decimal) -> _DayFigures:
    typed_till = row.fiscal_register if row else ZERO
    return _DayFigures(
        till=synced_till if synced_till is not None else typed_till,
        shop=shop,
        printer=row.fiscal_printer_total if row else None,
        # a typed non-zero till also counts: the salon may close a day by hand
        has_till=synced_till is not None or typed_till > 0 or shop > 0,
        explained_gap=row.recon_explained_gap if row and row.recon_explained else None,
    )


def _day_figures(db: Session, day: date, row: SalonDay | None) -> _DayFigures:
    nxt = day + timedelta(days=1)
    return _figures(
        row,
        booksy_till_by_day(db, day, nxt).get(day),
        shop_fiscal_by_day(db, day, nxt).get(day, ZERO),
    )


@salon_days.get("/reconciliation")
def month_reconciliation(db: DbDep, month: MonthQuery) -> list[MonthReconDayOut]:
    """Every day of the month that has a till: expected takings vs the fiscal
    printer. Registered BEFORE /{day} (a literal path must not be parsed as a date)."""
    start, end = month_bounds(month)
    shop = shop_fiscal_by_day(db, start, end)
    tills = booksy_till_by_day(db, start, end)
    out = []
    for r in month_days(db, start, end):
        f = _figures(r, tills.get(r.day), shop.get(r.day, ZERO))
        out.append(
            MonthReconDayOut(
                day=r.day,
                status=f.status,
                booksy_till=f.till,
                shop_sales=f.shop,
                fiscal_printer_total=f.printer,
                gap=f.gap,
            )
        )
    return out


def _txn_out(t: Txn) -> ReconTxnOut:
    return ReconTxnOut(
        doc=t.doc,
        client=t.client,
        performer=t.performer,
        cashier=t.cashier,
        method=t.method,
        amount=t.amount,
    )


def _recon_out(
    db: Session, day: date, row: SalonDay | None, is_admin: bool
) -> DayReconciliationOut:
    f = _day_figures(db, day, row)
    txns = day_txns(db, day) if is_admin else []
    return DayReconciliationOut(
        day=day,
        status=f.status,
        booksy_till=f.till,
        shop_sales=f.shop,
        fiscal_printer_total=f.printer,
        gap=f.gap,
        # the explanation may name a colleague → admin eyes only
        recon_note=row.recon_note if row and is_admin else None,
        synced=f.has_till,
        candidates=[[_txn_out(t) for t in g] for g in find_candidates(txns, f.gap or ZERO)],
        transactions=[_txn_out(t) for t in txns],
    )


@salon_days.get("/{day}/reconciliation")
def day_reconciliation(day: date, user: UserDep, db: DbDep) -> DayReconciliationOut:
    """Expected takings vs the fiscal printer for one day. A positive gap means
    something was settled in Booksy (or sold in the shop) but never rung up — the
    candidates are the transactions whose amount equals that gap, with the performer.

    Everyone at the desk sees THAT the day doesn't add up; only an admin sees the
    transactions, the names and the explanation — this page is shared by the whole
    team and a candidate list points at a colleague."""
    row = db.scalar(select(SalonDay).where(SalonDay.day == day))
    return _recon_out(db, day, row, "admin" in user.groups)


@salon_days.post("/{day}/reconciliation/explain", dependencies=[require_role("admin")])
def explain_gap(day: date, payload: ReconExplainIn, db: DbDep) -> DayReconciliationOut:
    """Admin only: accept (or re-open) a day's gap. The explanation is pinned to
    the CURRENT gap amount — if the gap later changes, the day is flagged again."""
    row = db.scalar(select(SalonDay).where(SalonDay.day == day))
    gap = _day_figures(db, day, row).gap
    if row is None or gap is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="brak raportu dobowego — nie ma czego wyjaśniać"
        )
    row.recon_explained = payload.explained
    row.recon_explained_gap = gap if payload.explained else None
    row.recon_note = (payload.note or "").strip() or None if payload.explained else None
    db.flush()
    return _recon_out(db, day, row, True)


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
    # Only what was actually sent: the day-close form doesn't know about the note
    # or the printer total of other screens, and must not blank them.
    sent = payload.model_fields_set
    if "note" in sent:
        row.note = payload.note
    if "fiscal_printer_total" in sent:
        row.fiscal_printer_total = payload.fiscal_printer_total
    db.flush()
    return _out(day, row, _unregistered(db, day))
