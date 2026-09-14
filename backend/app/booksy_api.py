"""Automatic Booksy pull (F5) — download the same report Booksy hands out as
xlsx and feed it through the EXISTING, tested xlsx parser. No second parser.

Booksy has no public API; this uses its internal business API the way the
browser does, authenticating with the three headers captured from a session
(x-access-token / x-api-key / x-fingerprint). The access token rotates (~daily),
so credentials live in a DB row the owner refreshes via an admin endpoint —
never in code or git. Uses stdlib urllib (a plain GET returning bytes) so the
runtime image gains no dependency.
"""

import io
import urllib.parse
import urllib.request
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.booksy import parse_visits_report
from app.models import BooksyCredential
from app.routers.imports import ImportSummary, import_visit_rows

REPORT_URL = (
    "https://pl.booksy.com/core/v2/business_api/me/stats/businesses/{business_id}/report/download"
)


class BooksyAuthError(RuntimeError):
    """No credentials configured, or Booksy rejected them (expired token)."""


@dataclass(frozen=True)
class BooksyCredentials:
    business_id: str
    access_token: str
    api_key: str
    fingerprint: str


def load_credentials(db: Session) -> BooksyCredentials:
    row = db.scalar(select(BooksyCredential).order_by(BooksyCredential.id).limit(1))
    if row is None:
        raise BooksyAuthError("brak zapisanych poświadczeń Booksy — ustaw token")
    return BooksyCredentials(
        business_id=row.business_id,
        access_token=row.access_token,
        api_key=row.api_key,
        fingerprint=row.fingerprint,
    )


def download_report(
    creds: BooksyCredentials,
    report_key: str,
    date_from: str,
    date_till: str,
    time_span: str = "month",
    timeout: int = 90,
) -> bytes:
    """GET the report/download endpoint → xlsx bytes. Mirrors the browser's
    request headers; a 401/403 means the session token has expired. The
    cash-registers report returns full history and is slow to generate, hence
    the generous default timeout."""
    params = urllib.parse.urlencode(
        {
            "date_from": date_from,
            "date_till": date_till,
            "time_span": time_span,
            "report_key": report_key,
        }
    )
    url = f"{REPORT_URL.format(business_id=creds.business_id)}?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "x-access-token": creds.access_token,
            "x-api-key": creds.api_key,
            "x-fingerprint": creds.fingerprint,
            "x-app-version": "3.0",
            "accept": "application/json, text/plain, */*",
            "user-agent": "charmskin-sync/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise BooksyAuthError("Booksy odrzucił poświadczenia — token wygasł, odśwież") from e
        raise BooksyAuthError(f"Booksy zwrócił HTTP {e.code}") from e


def pull_visits(db: Session, report_key: str, date_from: str, date_till: str) -> ImportSummary:
    """Download the visits report for a date range and upsert it — the same
    path as the manual xlsx upload, just fetched automatically."""
    creds = load_credentials(db)
    data = download_report(creds, report_key, date_from, date_till)
    rows = parse_visits_report(io.BytesIO(data))
    return import_visit_rows(db, rows)


def pull_registers(db: Session, date_from: str, date_till: str) -> dict:
    """Derive per-day salon-till figures (gotówka z Booksy + kasa fiskalna) from
    Booksy's cash-registers TRANSACTIONS report into salon_days. That report
    respects the URL date range (unlike the 'summary'), matches the owner's sheet
    to the złoty, and flags package redemptions. Authoritative for those two
    figures — replaces the range's salon_day rows (the ledger, i.e. 'gotówka nie
    wbita', lives elsewhere and is untouched)."""
    from datetime import date as _date

    from openpyxl import load_workbook
    from sqlalchemy import delete

    from app.models import SalonDay
    from app.registers import parse_cash_transactions

    creds = load_credentials(db)
    data = download_report(creds, "cash_registers_transactions", date_from, date_till)
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    grid = [list(r) for r in wb.active.iter_rows(values_only=True)]
    parsed = parse_cash_transactions(grid)

    start, end = _date.fromisoformat(date_from), _date.fromisoformat(date_till)
    days = {d: v for d, v in parsed.by_day.items() if start <= d <= end}
    db.execute(delete(SalonDay).where(SalonDay.day >= start, SalonDay.day <= end))
    for d, v in days.items():
        db.add(SalonDay(day=d, booksy_cash=v["booksy_cash"], fiscal_register=v["fiscal_register"]))
    db.flush()
    cash_total = sum((v["booksy_cash"] for v in days.values()), start=0)
    fiscal_total = sum((v["fiscal_register"] for v in days.values()), start=0)
    return {
        "days": len(days),
        "sessions": parsed.transactions,
        "package_redemptions": parsed.package_redemptions,
        "cash_total": str(cash_total),
        "fiscal_total": str(fiscal_total),
    }


def pull_packages(db: Session) -> dict:
    """Sync every client package from Booksy's packages_summary (Booksy is the
    source — packages are sold there). Upserts by Booksy package number; matches
    the client by name (link only, never creates). The report ignores dates and
    returns the full current state, which is what we want."""
    from openpyxl import load_workbook

    from app.booksy import split_name
    from app.models import Client, Package
    from app.packages import parse_packages_summary

    creds = load_credentials(db)
    data = download_report(creds, "packages_summary", "2026-01-01", "2026-12-31")
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    grid = [list(r) for r in wb.active.iter_rows(values_only=True)]
    parsed = parse_packages_summary(grid)

    created = updated = active = 0
    for p in parsed:
        first, last = split_name(p.client_name)
        client = db.scalar(
            select(Client).where(Client.first_name == first, Client.last_name == last)
        )
        row = db.scalar(select(Package).where(Package.booksy_number == p.booksy_number))
        if row is None:
            row = Package(booksy_number=p.booksy_number)
            db.add(row)
            created += 1
        else:
            updated += 1
        row.client_id = client.id if client else None
        row.client_name = p.client_name
        row.name = p.name
        row.total_value = p.total_value
        row.total_treatments = p.total_treatments
        row.remaining = p.remaining
        row.valid_from = p.valid_from
        row.valid_until = p.valid_until
        if p.remaining > 0:
            active += 1
    db.flush()
    return {"packages": len(parsed), "created": created, "updated": updated, "active": active}
