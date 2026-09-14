"""Monthly P&L — the profit side of the salon, reproducing the owner's sheet.

Two of the three inputs are DERIVED, never retyped:
  - Revenue (UTARG)          = money in the till = kasa fiskalna + gotówka
                               niewbita (salon_days), same as the kasa summary.
  - Staff cost (KOSZT PRAC.) = the month's settlement payouts (hours×rate +
                               commission); the fixed UOP/ZUS part sits in the
                               operating 'Koszty stałe' lines, as in the sheet.
Only operating costs are entered (Expense rows). The arithmetic mirrors the
sheet exactly:
    KOSZTY ŁĄCZNE       = Σ operating categories
    PODSUMOWANIE KOSZTÓW = KOSZTY ŁĄCZNE + KOSZT PRACOWNICY
    ZAROBEK             = UTARG − PODSUMOWANIE KOSZTÓW
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.derivation import month_bounds
from app.models import (
    ExpenseCategory,
    LedgerEntry,
    SalonDay,
    SettlementLine,
    SettlementPeriod,
)

# The owner's fixed cost columns — reference data, not user data. The migration
# seeds them (with ids the recurring seed references); this keeps them present
# even where schema comes from create_all (tests) or a skipped seed.
CATEGORY_SEED: list[tuple[str, str, int]] = [
    ("koszty_stale", "Koszty stałe", 1),
    ("koszty_zmienne", "Koszty zmienne", 2),
    ("koszty_jednorazowe", "Koszty art. jednorazowe", 3),
    ("paznokcie", "Paznokcie", 4),
    ("kosmetologia", "Kosmetologia", 5),
    ("kosmetyki_odsprzedaz", "Kosmetyki odsprzedaż", 6),
]


def ensure_categories(db: Session) -> None:
    """Idempotently create any missing cost category (by code)."""
    existing = set(db.scalars(select(ExpenseCategory.code)).all())
    missing = [(c, n, o) for c, n, o in CATEGORY_SEED if c not in existing]
    if missing:
        db.add_all(ExpenseCategory(code=c, name=n, display_order=o) for c, n, o in missing)
        db.flush()


def _sum(db: Session, col, *where) -> Decimal:
    return Decimal(str(db.scalar(select(func.coalesce(func.sum(col), 0)).where(*where))))


def month_money_total(db: Session, year_month: str) -> Decimal:
    """UTARG = kasa fiskalna + gotówka niewbita for the month (owner ruling:
    the same 'money in' figure as the daily kasa reconciliation)."""
    start, end = month_bounds(year_month)
    fiscal = _sum(db, SalonDay.fiscal_register, SalonDay.day >= start, SalonDay.day < end)
    unreg = _sum(
        db, LedgerEntry.amount_pln, LedgerEntry.entry_date >= start, LedgerEntry.entry_date < end
    )
    return fiscal + unreg


def month_staff_cost(db: Session, year_month: str) -> Decimal | None:
    """KOSZT PRACOWNICY = Σ the month's settlement payouts (an admin override on
    a line wins over the computed total). None when no period exists for the
    month — the caller then shows 0 and flags that settlement isn't entered."""
    period = db.scalar(select(SettlementPeriod).where(SettlementPeriod.year_month == year_month))
    if period is None:
        return None
    return _sum(
        db,
        func.coalesce(SettlementLine.override_total, SettlementLine.total_payout),
        SettlementLine.period_id == period.id,
    )


@dataclass(frozen=True)
class PnlTotals:
    revenue: Decimal
    operating_total: Decimal  # KOSZTY ŁĄCZNE
    staff_cost: Decimal  # KOSZT PRACOWNICY
    costs_total: Decimal  # PODSUMOWANIE KOSZTÓW
    profit: Decimal  # ZAROBEK


def totals(revenue: Decimal, category_totals: dict[str, Decimal], staff_cost: Decimal) -> PnlTotals:
    """Pure P&L arithmetic — the sheet's formula, given the pieces."""
    operating = sum(category_totals.values(), Decimal("0"))
    costs = operating + staff_cost
    return PnlTotals(
        revenue=revenue,
        operating_total=operating,
        staff_cost=staff_cost,
        costs_total=costs,
        profit=revenue - costs,
    )
