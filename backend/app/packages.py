"""Parser for Booksy's 'packages_summary' report — the current state of every
client package. Booksy is the source of truth (packages are entered there); we
sync definitions + remaining + expiry.

Columns (0-indexed): 3 client, 4 name, 5 booksy number (unique), 6 price,
7 'X / Y' (X remaining of Y total treatments), 8 valid_from, 9 valid_until.
value_per_treatment = price / Y. Confirmed on real data: expired rows show
'0 / Y'; the name is unreliable for the count (denominator Y is authoritative).
Pure/DB-free.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

_C = {"client": 3, "name": 4, "number": 5, "price": 6, "value": 7, "from": 8, "until": 9}


@dataclass(frozen=True)
class ParsedPackage:
    booksy_number: str
    client_name: str
    name: str
    total_value: Decimal
    total_treatments: int
    remaining: int
    valid_from: date | None
    valid_until: date | None


def _date(cell: object) -> date | None:
    if cell is None:
        return None
    head = str(cell).strip()
    parts = head.split(".")
    if len(parts) != 3:
        return None
    try:
        d, m, y = (int(p) for p in parts)
        return date(y, m, d)
    except ValueError:
        return None


def _money(cell: object) -> Decimal | None:
    try:
        return Decimal(str(cell).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def _remaining_total(cell: object) -> tuple[int, int] | None:
    """'5 / 15' → (5, 15) = (remaining, total)."""
    s = str(cell).strip() if cell is not None else ""
    if "/" not in s:
        return None
    a, _, b = s.partition("/")
    try:
        return int(a.strip()), int(b.strip())
    except ValueError:
        return None


def parse_packages_summary(grid: list[list[object]]) -> list[ParsedPackage]:
    out: list[ParsedPackage] = []
    for r in grid:
        if len(r) <= _C["until"]:
            continue
        number = str(r[_C["number"]]).strip() if r[_C["number"]] is not None else ""
        if not number.isdigit():  # data rows carry a numeric Booksy package id
            continue
        rt = _remaining_total(r[_C["value"]])
        price = _money(r[_C["price"]])
        name = str(r[_C["name"]]).strip() if r[_C["name"]] is not None else ""
        client = str(r[_C["client"]]).strip() if r[_C["client"]] is not None else ""
        if rt is None or price is None or not client:
            continue
        remaining, total = rt
        if total <= 0:
            continue
        out.append(
            ParsedPackage(
                booksy_number=number,
                client_name=client,
                name=name,
                total_value=price,
                total_treatments=total,
                remaining=remaining,
                valid_from=_date(r[_C["from"]]),
                valid_until=_date(r[_C["until"]]),
            )
        )
    return out
