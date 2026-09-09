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
) -> bytes:
    """GET the report/download endpoint → xlsx bytes. Mirrors the browser's
    request headers; a 401/403 means the session token has expired."""
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
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https host)
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
