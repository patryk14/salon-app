"""Parser for the Booksy Biz "Lista wizyt" xlsx report.

Report anatomy (as exported 2026-09): a title block, salon address, date range,
then a header row (row 8 today — located dynamically by column NAMES, so a
Booksy template change moves rows without breaking us), then data rows.

Facts we ingest: who / when / what / for how much / status / staff.
Aggregates (netto, tax, tips) are ignored — anything derivable is computed on
our side, so the panel can never disagree with itself.

No Booksy report exposes phone/email; clients are keyed by their display name
and contact data is filled in manually in the panel.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import BinaryIO
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

SALON_TZ = ZoneInfo("Europe/Warsaw")

# Header cells that identify the visits report; all must be present in one row.
REQUIRED_COLUMNS = {"Data i godzina", "ID rezerwacji", "Usługa", "Klient", "Status"}
OPTIONAL_COLUMNS = {"Pracownik", "Przychód"}

STATUS_MAP = {
    "Zakończone": "completed",
    "Anulowane": "cancelled",
    "Nieobecność": "no_show",
}


class BooksyParseError(ValueError):
    """The file is not a recognizable 'Lista wizyt' export."""


@dataclass(frozen=True)
class VisitRow:
    booksy_ref: str
    client_name: str
    starts_at: datetime
    service_name: str
    status: str
    price_pln: Decimal | None
    staff_name: str | None


def _find_header(rows: list[tuple]) -> tuple[int, dict[str, int]]:
    for i, row in enumerate(rows):
        names = {str(v): idx for idx, v in enumerate(row) if v is not None}
        if names.keys() >= REQUIRED_COLUMNS:
            return i, names
    raise BooksyParseError(
        "header row not found — expected columns: " + ", ".join(sorted(REQUIRED_COLUMNS))
    )


def parse_visits_report(fileobj: BinaryIO) -> list[VisitRow]:
    wb = load_workbook(fileobj, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

    header_idx, cols = _find_header(rows)
    visits: list[VisitRow] = []

    for row in rows[header_idx + 1 :]:
        ref = row[cols["ID rezerwacji"]] if cols["ID rezerwacji"] < len(row) else None
        # Footer/total rows have no reservation id — the data block is over.
        if ref is None or not str(ref).strip().isdigit():
            continue

        raw_date = str(row[cols["Data i godzina"]]).strip()
        try:
            starts_at = datetime.strptime(raw_date, "%d.%m.%Y %H:%M").replace(tzinfo=SALON_TZ)
        except ValueError as e:
            raise BooksyParseError(f"unparseable date {raw_date!r} in row with id {ref}") from e

        raw_price = row[cols["Przychód"]] if "Przychód" in cols else None
        price = Decimal(str(raw_price)) if raw_price is not None else None

        staff = row[cols["Pracownik"]] if "Pracownik" in cols else None

        visits.append(
            VisitRow(
                booksy_ref=str(ref),
                client_name=str(row[cols["Klient"]]).strip(),
                starts_at=starts_at,
                service_name=str(row[cols["Usługa"]]).strip(),
                # Unknown status (a future Booksy label) degrades to 'scheduled'
                # rather than failing the whole import.
                status=STATUS_MAP.get(str(row[cols["Status"]]).strip(), "scheduled"),
                price_pln=price,
                staff_name=str(staff).strip() if staff else None,
            )
        )

    return visits


def split_name(full_name: str) -> tuple[str, str]:
    """'Anna Maria Kowalska' → ('Anna', 'Maria Kowalska').

    Booksy exports display names as '<first> <rest>'; the first token is the
    given name, everything else the surname. Single-token names get '?' as the
    surname placeholder — visible in the panel, fixable by a human.
    """
    parts = full_name.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return (full_name or "?", "?")
