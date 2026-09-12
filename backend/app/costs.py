"""Parser for the monthly 'zabiegi_koszty' cash till sheet.

Layout (confirmed against the owner's live sheet, used 1+ year):
  row 0:            "", 1, 2, ... 31            (day-of-month columns)
  per employee:     <Name>                      (marker row, alias-resolvable)
                    Zabieg 1..4                  (one cash-paying client per cell)
                    SUMA <Name>                  (daily sums — ignored, checksum)
  reconciliation:   Gotowka nie wbita            (Σ employees' cash — derived, checksum)
                    Gotowka z booksy             (cash taken via Booksy → salon_day)
                    Suma gotowki w Kasie         (ignored)
                    Kasa fiskalna                (POS day total → salon_day)
                    Suma                         (ignored)
  OPIS ...          (free-text notes — parsing stops here)

Off-Booksy cash ('gotówka nie wbita') exists ONLY in this sheet — Booksy never
has it. The sheet carries no year/month, so the caller supplies year_month.
Pure and DB-free: takes the grid + a name→employee_id resolver.
"""

import calendar
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation


@dataclass
class ParsedCosts:
    # (employee_id, entry_date, amount) — one per non-empty Zabieg cell.
    ledger: list[tuple[int, date, Decimal]] = field(default_factory=list)
    # entry_date -> {"booksy_cash": Decimal, "fiscal_register": Decimal}
    salon_days: dict[date, dict[str, Decimal]] = field(default_factory=dict)
    per_employee: dict[int, Decimal] = field(default_factory=dict)  # id -> month sum
    unmatched_names: list[str] = field(default_factory=list)
    # From the "Gotowka nie wbita" row — used to cross-check our Σ ledger per day.
    unregistered_by_day: dict[date, Decimal] = field(default_factory=dict)


def _num(cell: object) -> Decimal | None:
    """Parse a money cell; None for empty/zero/garbage (empty cells are the norm)."""
    if cell is None:
        return None
    s = str(cell).strip().replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return v if v != 0 else None


def _day_columns(header: list[object]) -> dict[int, int]:
    """Map column index -> day number, from a header row's 1..31 cells."""
    cols: dict[int, int] = {}
    for i, cell in enumerate(header):
        s = str(cell).strip() if cell is not None else ""
        if s.replace(".0", "").isdigit():
            d = int(float(s))
            if 1 <= d <= 31:
                cols[i] = d
    return cols


def find_header_row(grid: list[list[object]]) -> int | None:
    """The day-number header may not be the first row (title rows, merged cells).
    Find the first row that carries a run of day numbers 1..31."""
    for idx, row in enumerate(grid[:20]):
        if len(_day_columns(row)) >= 8:
            return idx
    return None


def parse_costs(
    grid: list[list[object]],
    year: int,
    month: int,
    resolve: Callable[[str], int | None],
) -> ParsedCosts:
    out = ParsedCosts()
    hdr = find_header_row(grid)
    if hdr is None:
        return out
    day_cols = _day_columns(grid[hdr])
    last_day = calendar.monthrange(year, month)[1]  # skip col 31 in a 30-day month

    def day_cells(row: list[object]):
        for i, day in day_cols.items():
            if day > last_day or i >= len(row):
                continue
            v = _num(row[i])
            if v is not None:
                yield date(year, month, day), v

    current_emp: int | None = None
    for row in grid[hdr + 1 :]:
        first = str(row[0]).strip() if row and row[0] is not None else ""
        low = first.lower()
        if not first:
            continue
        if low.startswith("opis") or len(first) > 40:
            break  # free-text notes region — done
        if low.startswith("zabieg"):
            if current_emp is not None:
                for d, v in day_cells(row):
                    out.ledger.append((current_emp, d, v))
                    out.per_employee[current_emp] = (
                        out.per_employee.get(current_emp, Decimal("0")) + v
                    )
            continue
        if low.startswith("suma"):  # "SUMA <Name>" / "Suma gotowki w Kasie" / "Suma"
            continue
        if low.startswith("gotowka nie wbita"):
            for d, v in day_cells(row):
                out.unregistered_by_day[d] = v
            continue
        if low.startswith("gotowka z booksy"):
            for d, v in day_cells(row):
                out.salon_days.setdefault(d, {}).setdefault("booksy_cash", Decimal("0"))
                out.salon_days[d]["booksy_cash"] += v
            continue
        if low.startswith("kasa fiskalna"):
            for d, v in day_cells(row):
                out.salon_days.setdefault(d, {}).setdefault("fiscal_register", Decimal("0"))
                out.salon_days[d]["fiscal_register"] += v
            continue
        # Otherwise it's an employee marker row.
        emp_id = resolve(first)
        if emp_id is None:
            out.unmatched_names.append(first)
            current_emp = None
        else:
            current_emp = emp_id
    return out
