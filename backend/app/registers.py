"""Parser for Booksy's 'cash_registers_summary' report — the closed till
sessions (open→close), from which we DERIVE the daily register figures:

  gotówka z Booksy = closing cash − opening cash   (cash sales)
  kasa fiskalna    = Razem − opening = cash + card  (all sales through the till)

Confirmed against the owner's sheet day-by-day. The report ignores the URL date
range (returns everything since 2024), so the caller filters by CLOSING date.
Only CLOSED sessions count. Pure/DB-free: grid in, per-day figures out.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation


@dataclass
class ParsedRegisters:
    # closing_date -> {"booksy_cash": cash sales, "fiscal_register": cash + card}
    by_day: dict[date, dict[str, Decimal]] = field(default_factory=dict)
    sessions: int = 0


def _num(cell: object) -> Decimal:
    if cell is None:
        return Decimal("0")
    try:
        return Decimal(str(cell).strip().replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def _close_date(cell: object) -> date | None:
    """'1.09.2026 19:30' → date(2026, 9, 1). None if unparseable."""
    if cell is None:
        return None
    head = str(cell).strip().split()[0] if str(cell).strip() else ""
    parts = head.split(".")
    if len(parts) != 3:
        return None
    try:
        d, m, y = (int(p) for p in parts)
        return date(y, m, d)
    except ValueError:
        return None


def parse_cash_registers(grid: list[list[object]]) -> ParsedRegisters:
    out = ParsedRegisters()
    # header row carries "Status"; columns are fixed by Booksy's export.
    hdr_i = next(
        (i for i, r in enumerate(grid) if any(str(c).strip() == "Status" for c in r if c)),
        None,
    )
    if hdr_i is None:
        return out
    C = {  # column indexes in the Booksy export
        "status": 2,
        "closed": 4,
        "open_cash": 6,
        "close_cash": 8,
        "other": 11,
        "total": 13,
    }
    for r in grid[hdr_i + 1 :]:
        if len(r) <= C["total"]:
            continue
        if str(r[C["status"]]).strip() != "Zamknięty":  # only closed sessions
            continue
        day = _close_date(r[C["closed"]])
        if day is None:
            continue
        cash = _num(r[C["close_cash"]]) - _num(r[C["open_cash"]])
        fiscal = _num(r[C["total"]]) - _num(r[C["open_cash"]])  # = cash + card
        agg = out.by_day.setdefault(
            day, {"booksy_cash": Decimal("0"), "fiscal_register": Decimal("0")}
        )
        agg["booksy_cash"] += cash
        agg["fiscal_register"] += fiscal
        out.sessions += 1
    return out
