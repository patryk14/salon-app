"""Fiscal reconciliation — did everything settled in Booksy reach the register?

Booksy's till ("kasa" = cash + card inflow) and the fiscal printer's daily report
should agree. When a treatment is settled in Booksy but never rung up, Booksy's
till is higher by exactly that amount — so the gap itself points at the culprit:
we look for the Booksy transaction (or pair) whose amount equals the gap, and name
the performer from that client's visit that day (the till row only ever names the
shared cashier). Pure helpers first; the DB glue is at the bottom.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Client, RegisterTxn, SalonDay, Visit

TOLERANCE = Decimal("0.01")
MAX_CANDIDATES = 8


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
    """Transactions that explain a POSITIVE gap (Booksy > register): every single
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


def status_of(printer: Decimal | None, gap: Decimal | None, explained: bool) -> str:
    if printer is None:
        return "no_report"  # nobody typed the daily fiscal report yet
    if gap is not None and abs(gap) <= TOLERANCE:
        return "ok"
    return "explained" if explained else "gap"


# ------------------------------------------------------------------- DB glue
def _performers(db: Session, day: date) -> dict[str, str]:
    """client name (lowercased) → performer, from that day's visits."""
    rows = db.execute(
        select(Client.first_name, Client.last_name, Visit.staff_name)
        .join(Visit, Visit.client_id == Client.id)
        .where(Visit.starts_at >= day, Visit.starts_at < day + timedelta(days=1))
    ).all()
    return {f"{first} {last}".strip().lower(): staff for first, last, staff in rows if staff}


def day_txns(db: Session, day: date) -> list[Txn]:
    performers = _performers(db, day)
    rows = db.scalars(select(RegisterTxn).where(RegisterTxn.day == day).order_by(RegisterTxn.id))
    return [
        Txn(
            doc=r.doc,
            client=r.client_name,
            cashier=r.staff_name,
            method=r.method,
            amount=r.inflow,
            performer=performers.get((r.client_name or "").strip().lower()),
        )
        for r in rows
    ]


def month_days(db: Session, start: date, end: date) -> list[SalonDay]:
    return list(
        db.scalars(
            select(SalonDay).where(SalonDay.day >= start, SalonDay.day < end).order_by(SalonDay.day)
        )
    )


def txn_count(db: Session, day: date) -> int:
    return int(db.scalar(select(func.count(RegisterTxn.id)).where(RegisterTxn.day == day)) or 0)
