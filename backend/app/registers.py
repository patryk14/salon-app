"""Parser for Booksy's 'cash_registers_transactions' report — one row per till
transaction, with the payment method. From it we derive the daily till figures:

  gotówka z Booksy = Σ Wpływy where method = Gotówka
  kasa fiskalna    = Σ Wpływy (all methods; Pakiet rows are 0)  == cash + card
  (card is the remainder; Pakiet rows flag package redemptions for later)

Unlike the 'summary' report this one RESPECTS the URL date range and matches the
owner's sheet to the złoty (it uses gross inflow, not close−open). Pure/DB-free.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

# Column indexes in Booksy's transactions export.
_C = {"doc": 3, "date": 2, "client": 5, "staff": 6, "inflow": 7, "outflow": 8, "method": 9}


@dataclass(frozen=True)
class RegisterRow:
    day: date
    doc: str
    client: str
    staff: str
    method: str
    inflow: Decimal
    outflow: Decimal


@dataclass
class ParsedRegisters:
    # closing/transaction date -> {"booksy_cash": cash, "fiscal_register": cash+card}
    by_day: dict[date, dict[str, Decimal]] = field(default_factory=dict)
    transactions: int = 0
    package_redemptions: int = 0  # count of 'Pakiet' rows
    # (redemption_date, client_name, doc_number) per 'Pakiet' row — for crediting
    # package commission to the day's performer.
    package_txs: list[tuple[date, str, str]] = field(default_factory=list)
    # every transaction row, for tracing a fiscal gap to its cause
    rows: list[RegisterRow] = field(default_factory=list)


def _num(cell: object) -> Decimal:
    if cell is None:
        return Decimal("0")
    try:
        return Decimal(str(cell).strip().replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def _tx_date(cell: object) -> date | None:
    """'12.09.2026 13:05' → date(2026, 9, 12). None if unparseable."""
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


def parse_cash_transactions(grid: list[list[object]]) -> ParsedRegisters:
    out = ParsedRegisters()
    hdr_i = next(
        (i for i, r in enumerate(grid) if any(str(c).strip() == "Data transakcji" for c in r if c)),
        None,
    )
    if hdr_i is None:
        return out
    for r in grid[hdr_i + 1 :]:
        if len(r) <= _C["method"]:
            continue
        day = _tx_date(r[_C["date"]])
        if day is None:  # skips the trailing "Razem" total row and blanks
            continue
        method = str(r[_C["method"]]).strip().lower()
        inflow = _num(r[_C["inflow"]])

        def _s(key: str, row=r) -> str:
            return str(row[_C[key]]).strip() if row[_C[key]] is not None else ""

        out.rows.append(
            RegisterRow(
                day=day,
                doc=_s("doc"),
                client=_s("client"),
                staff=_s("staff"),
                method=_s("method"),
                inflow=inflow,
                outflow=_num(r[_C["outflow"]]),
            )
        )
        agg = out.by_day.setdefault(
            day, {"booksy_cash": Decimal("0"), "fiscal_register": Decimal("0")}
        )
        agg["fiscal_register"] += inflow  # all methods (Pakiet is 0)
        if method.startswith("got"):  # "Gotówka"
            agg["booksy_cash"] += inflow
        if "pakiet" in method:
            out.package_redemptions += 1
            client = str(r[_C["client"]]).strip() if r[_C["client"]] is not None else ""
            doc = str(r[_C["doc"]]).strip() if r[_C["doc"]] is not None else ""
            out.package_txs.append((day, client, doc))
        out.transactions += 1
    return out
