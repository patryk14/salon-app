"""Best-effort seed of the vouchers list from the owner's VOUCHERY.docx.

The doc is a hand-kept table (IMIĘ | USŁUGA/KWOTA | DATA ZAKUPU | DATA WAŻNOŚCI
| WYKORZYSTANY) with free-form status prose. We parse only the MACHINE-readable
fields — name, złoty value, purchase + validity dates — and leave remaining
value = total (the owner adjusts partially-used ones in the review). The prose
'WYKORZYSTANY' column is deliberately NOT parsed; it's unreliable. Pure/DB-free.
"""

import re
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")
_VALUE = re.compile(r"(\d[\d\s]{0,7})\s*z[łl]", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedVoucher:
    client_name: str
    description: str
    total_value: Decimal
    purchased_on: date | None
    valid_until: date | None


def _cell_text(tc) -> str:
    return " ".join(
        "".join(t.text or "" for t in p.iter(f"{_W}t")).strip() for p in tc.findall(f"{_W}p")
    ).strip()


def _date(cell: str) -> date | None:
    m = _DATE.search(cell or "")
    if not m:
        return None
    d, mth, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def _value(cell: str) -> Decimal | None:
    m = _VALUE.search(cell or "")
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(" ", ""))
    except InvalidOperation:
        return None


def parse_vouchers_docx(raw: bytes) -> list[ParsedVoucher]:
    with zipfile.ZipFile(_bytes_io(raw)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    out: list[ParsedVoucher] = []
    for tbl in root.iter(f"{_W}tbl"):
        for tr in tbl.findall(f"{_W}tr"):
            cells = [_cell_text(tc) for tc in tr.findall(f"{_W}tc")]
            if len(cells) < 4:
                continue
            client, desc, bought, valid = cells[0], cells[1], cells[2], cells[3]
            if not client or client.upper().startswith("IMIĘ"):  # empty or header row
                continue
            value = _value(desc)
            if value is None:  # can't price it → skip (owner can add by hand)
                continue
            out.append(
                ParsedVoucher(
                    client_name=client,
                    description=desc,
                    total_value=value,
                    purchased_on=_date(bought),
                    valid_until=_date(valid),
                )
            )
    return out


def _bytes_io(raw: bytes):
    import io

    return io.BytesIO(raw)
