"""MT940 (.sta) bank-statement parser — the cost side from the bank.

ING exports `.sta` in the MT940 SWIFT format, CP852-encoded. We extract the
DEBITS (money out = expense candidates); credits are the revenue side (card
settlements, cash deposits) already covered by the kasa. Each debit gets a
suggested category from a keyword table; ambiguous ones (payment aggregators)
and the special buckets (staff salaries, owner draws) are flagged for manual
review — they never silently become operating costs.

Pure/DB-free: bytes in, ParsedTxn list out.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# (keyword in counterparty+title UPPER, category_code | None, label, bucket).
# First match wins — order matters (specific counterparties before generic
# title words, e.g. SFERA before WYNAJEM). category_code None = needs a human.
_RULES: list[tuple[str, str | None, str, str]] = [
    ("WYNAGRODZENIE", None, "Wynagrodzenie", "staff"),
    ("KONTO PRYWATNE", None, "Przelew własny", "owner_draw"),
    ("ZUS", "koszty_stale", "ZUS", "operating"),
    ("URZĄD SKARBOWY", "koszty_stale", "Podatek (US)", "operating"),
    ("FACEBK", "koszty_zmienne", "Reklama Facebook", "operating"),
    ("CANVA", "koszty_stale", "Canva", "operating"),
    ("EXPERMUSIC", "koszty_stale", "Muzyka", "operating"),
    ("BOOKSY", "koszty_stale", "Booksy", "operating"),
    ("RACH-M", "koszty_stale", "Księgowa", "operating"),
    ("SFERA", "koszty_stale", "Leasing endermologia", "operating"),
    ("PKOL", "koszty_stale", "RF leasing", "operating"),
    ("LEASELINK", "koszty_stale", "Leasing (LeaseLink)", "operating"),
    ("MEDIA", "koszty_stale", "Media / rachunki", "operating"),
    ("WYNAJEM", "koszty_stale", "Najem", "operating"),
    ("VASTUM", "koszty_stale", "Odpady medyczne", "operating"),
    ("GIGA", "koszty_stale", "Internet", "operating"),
    ("CULLIGAN", "koszty_jednorazowe", "Woda dla klienta", "operating"),
    ("P4 SP", "koszty_stale", "Telefon (Play)", "operating"),
    ("24.PLAY", "koszty_stale", "Telefon (Play)", "operating"),
    ("IQNAILS", "paznokcie", "Materiały paznokcie", "operating"),
    ("PIMPMYLASHES", "kosmetologia", "Materiały (rzęsy)", "operating"),
    ("SKINSOLUTION", "kosmetologia", "Kosmetyki", "operating"),
    ("ABAGROUP", "kosmetologia", "Kosmetyki", "operating"),
    ("HURTOWNIA ESTETYCZNA", "kosmetologia", "Hurtownia estetyczna", "operating"),
    ("BIEDRONKA", "koszty_jednorazowe", "Art. spożywcze", "operating"),
    ("ROSSMANN", "koszty_jednorazowe", "Drogeria", "operating"),
    ("OLX", "koszty_zmienne", "OLX", "operating"),
    # payment aggregators hide the real merchant → always manual:
    ("ALLEGRO", None, "Allegro", "unknown"),
    ("PAYU", None, "PayU", "unknown"),
    ("PAYPRO", None, "PayPro", "unknown"),
]


@dataclass(frozen=True)
class ParsedTxn:
    bank_ref: str  # bank's own transaction id — the dedup key
    value_date: date
    amount: Decimal  # positive; money out
    counterparty: str
    title: str
    suggested_category: str | None  # one of the 6 category codes, else None
    suggested_name: str  # the line label
    bucket: str  # operating | staff | owner_draw | unknown


def _suggest(counterparty: str, title: str) -> tuple[str | None, str, str]:
    text = f"{counterparty} {title}".upper()
    for kw, cat, label, bucket in _RULES:
        if kw in text:
            return cat, label, bucket
    return None, (counterparty.split("  ")[0].strip() or "nieznane"), "unknown"


def _join(body: str, pattern: str) -> str:
    return re.sub(r"\s+", " ", " ".join(re.findall(pattern, body))).strip()


def parse_mt940(raw: bytes) -> list[ParsedTxn]:
    """Every debit in the statement, with a suggested category. Credits skipped."""
    text = raw.decode("cp852")
    out: list[ParsedTxn] = []
    for chunk in re.split(r"(?=^:61:)", text, flags=re.MULTILINE):
        m = re.match(r":61:(\d{2})(\d{2})(\d{2})\d{4}([DC])(\d+,\d{2})([^\r\n]*)", chunk)
        if not m:
            continue
        yy, mm, dd, dc, amt, ref = m.groups()
        if dc != "D":  # credits = revenue side, not expenses
            continue
        counterparty = _join(chunk, r"~3[23]([^~\r\n]*)")
        title = _join(chunk, r"~2[012345]([^~\r\n]*)")
        cat, label, bucket = _suggest(counterparty, title)
        out.append(
            ParsedTxn(
                bank_ref=ref.strip(),
                value_date=date(2000 + int(yy), int(mm), int(dd)),
                amount=Decimal(amt.replace(",", ".")),
                counterparty=counterparty,
                title=title,
                suggested_category=cat,
                suggested_name=label,
                bucket=bucket,
            )
        )
    return out
