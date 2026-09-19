"""Fiscal reconciliation — did everything that was sold reach the register?

Booksy's till (cash + card inflow) plus the cash/card product sales made in the
app's shop is what the fiscal printer's daily report SHOULD show. When a treatment
is settled in Booksy (or a product is sold) but never rung up, the expected total
is higher by exactly that amount — so the gap itself points at the culprit: we
look for the transaction (or pair) whose amount equals the gap, and name the
performer from that client's visit that day (the till row only ever names the
shared cashier). Pure helpers first; the DB glue is at the bottom.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Client, Employee, ProductSale, RegisterTxn, SalonDay, Visit

TOLERANCE = Decimal("0.01")
MAX_CANDIDATES = 8
FISCAL_PAYMENTS = ("gotowka", "karta")  # shop payment methods that pass the register


@dataclass(frozen=True)
class Txn:
    doc: str | None
    client: str | None
    cashier: str | None
    method: str | None
    amount: Decimal
    performer: str | None = None


def is_fiscal(method: str | None) -> bool:
    """Only money that must pass the fiscal register: cash and card. Package /
    voucher redemptions are 0-value rows (the money was taken when sold)."""
    m = (method or "").lower()
    return not any(word in m for word in ("pakiet", "voucher", "bon", "karta podarunkowa"))


def find_candidates(txns: list[Txn], gap: Decimal) -> list[list[Txn]]:
    """Transactions that explain a POSITIVE gap (expected > register): every single
    transaction equal to the gap, else every pair summing to it. Exact matches
    only — a near-miss would accuse the wrong person."""
    if gap <= TOLERANCE:
        return []
    pool = [t for t in txns if t.amount > 0 and is_fiscal(t.method)]
    singles = [[t] for t in pool if abs(t.amount - gap) <= TOLERANCE]
    if singles:
        return singles[:MAX_CANDIDATES]
    pairs = [
        [a, b] for a, b in combinations(pool, 2) if abs(a.amount + b.amount - gap) <= TOLERANCE
    ]
    return pairs[:MAX_CANDIDATES]


def status_of(
    printer: Decimal | None,
    gap: Decimal | None,
    explained_gap: Decimal | None,
    has_till: bool = True,
) -> str:
    """no_report → nobody typed the fiscal report · not_synced → the report is in
    but we hold no Booksy till for that day yet (comparing would show the whole
    day as a bogus gap) · ok · explained (ONLY while the gap still equals the
    amount that was explained) · gap."""
    if printer is None or gap is None:
        return "no_report"
    if not has_till:
        return "not_synced"
    if abs(gap) <= TOLERANCE:
        return "ok"
    if explained_gap is not None and abs(gap - explained_gap) <= TOLERANCE:
        return "explained"
    return "gap"


def norm_name(value: str | None) -> str:
    return " ".join((value or "").lower().split())


# ------------------------------------------------------------------- DB glue
def _performers(db: Session, day: date) -> dict[str, str]:
    """client name → who performed her visit(s) that day. Cancelled / no-show
    visits don't count (nobody performed them), and when a client saw more than
    one person we say so ("Julia / Oliwia") rather than pick one — this list can
    put a colleague under suspicion, so it must never guess."""
    rows = db.execute(
        select(Client.first_name, Client.last_name, Visit.staff_name)
        .join(Visit, Visit.client_id == Client.id)
        .where(
            Visit.starts_at >= day,
            Visit.starts_at < day + timedelta(days=1),
            Visit.status.not_in(("cancelled", "no_show")),
        )
    ).all()
    found: dict[str, set[str]] = {}
    for first, last, staff in rows:
        if not staff:
            continue
        # Booksy's till writes "First Last"; tolerate "Last First" and odd spacing.
        for key in (norm_name(f"{first} {last}"), norm_name(f"{last} {first}")):
            found.setdefault(key, set()).add(staff.strip())
    return {name: " / ".join(sorted(staff)) for name, staff in found.items()}


def day_txns(db: Session, day: date) -> list[Txn]:
    """Everything that should have been rung up that day: Booksy's till rows plus
    the cash/card product sales made in the app's shop (so an un-rung PRODUCT is
    never pinned on an unrelated treatment of the same amount)."""
    performers = _performers(db, day)
    rows = db.scalars(select(RegisterTxn).where(RegisterTxn.day == day).order_by(RegisterTxn.id))
    out = [
        Txn(
            doc=r.doc,
            client=r.client_name,
            cashier=r.staff_name,
            method=r.method,
            amount=r.inflow,
            performer=performers.get(norm_name(r.client_name)),
        )
        for r in rows
    ]
    sales = db.execute(
        select(ProductSale, Employee.display_name)
        .outerjoin(Employee, Employee.id == ProductSale.employee_id)
        .where(ProductSale.sold_on == day, ProductSale.payment_method.in_(FISCAL_PAYMENTS))
        .order_by(ProductSale.id)
    ).all()
    out += [
        Txn(
            doc=f"sklep #{s.id}",
            client=None,
            cashier=None,
            method=f"sklep · {s.product_name} ({s.payment_method})",
            amount=s.total,
            performer=seller,
        )
        for s, seller in sales
    ]
    return out


def month_days(db: Session, start: date, end: date) -> list[SalonDay]:
    return list(
        db.scalars(
            select(SalonDay).where(SalonDay.day >= start, SalonDay.day < end).order_by(SalonDay.day)
        )
    )


def shop_fiscal_by_day(db: Session, start: date, end: date) -> dict[date, Decimal]:
    """Cash/card product sales made in the app's shop, per day in [start, end).
    They pass the fiscal register but are invisible to Booksy, so the register is
    EXPECTED to exceed Booksy's till by exactly this much."""
    rows = db.execute(
        select(ProductSale.sold_on, func.sum(ProductSale.total))
        .where(
            ProductSale.sold_on >= start,
            ProductSale.sold_on < end,
            ProductSale.payment_method.in_(FISCAL_PAYMENTS),
        )
        .group_by(ProductSale.sold_on)
    ).all()
    return {d: Decimal(str(total)) for d, total in rows}


def booksy_till_by_day(db: Session, start: date, end: date) -> dict[date, Decimal]:
    """Booksy's till per day, summed from the KEPT transaction rows. Days present
    here are 'synced'. Preferred over salon_days.fiscal_register, which anyone at
    the desk can retype — an anti-fraud figure must not be editable by the people
    it checks."""
    rows = db.execute(
        select(RegisterTxn.day, func.sum(RegisterTxn.inflow))
        .where(RegisterTxn.day >= start, RegisterTxn.day < end)
        .group_by(RegisterTxn.day)
    ).all()
    return {d: Decimal(str(total)) for d, total in rows}
