"""Booksy xlsx import.

Idempotent by design: `booksy_ref` (Booksy reservation id) is unique in the
visits table, so re-uploading the same or an overlapping report UPDATES
existing rows instead of duplicating them. Clients are matched by display name
(the only identity Booksy reports expose) and created on first sight.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.booksy import BooksyParseError, VisitRow, parse_visits_report, split_name
from app.deps import get_db
from app.models import BooksyCredential, Client, Visit

logger = logging.getLogger(__name__)

# Imports mutate the whole dataset (creates clients, rewrites visits) — owner only.
router = APIRouter(prefix="/imports", tags=["imports"], dependencies=[require_role("admin")])


class ImportSummary(BaseModel):
    visits_in_file: int
    clients_created: int
    visits_created: int
    visits_updated: int


class BooksyCredentialsIn(BaseModel):
    business_id: str = Field(default="221497", max_length=20)
    access_token: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=1, max_length=200)
    fingerprint: str = Field(min_length=1, max_length=200)


class PullRequest(BaseModel):
    # report_key identifies WHICH Booksy report to download (the visits list).
    report_key: str = Field(min_length=1, max_length=100)
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_till: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


def _client_for(db: Session, cache: dict[str, Client], name: str) -> tuple[Client, bool]:
    if name in cache:
        return cache[name], False
    first, last = split_name(name)
    existing = db.scalars(
        select(Client).where(Client.first_name == first, Client.last_name == last)
    ).first()
    if existing is not None:
        cache[name] = existing
        return existing, False
    client = Client(first_name=first, last_name=last)
    db.add(client)
    db.flush()
    cache[name] = client
    return client, True


def _upsert_visit(db: Session, client: Client, row: VisitRow) -> bool:
    """Returns True when a new visit was created, False on update."""
    visit = db.scalars(select(Visit).where(Visit.booksy_ref == row.booksy_ref)).first()
    if visit is None:
        db.add(
            Visit(
                client_id=client.id,
                booksy_ref=row.booksy_ref,
                starts_at=row.starts_at,
                service_name=row.service_name,
                status=row.status,
                price_pln=row.price_pln,
                staff_name=row.staff_name,
            )
        )
        return True
    # Booksy is the source of truth for its own fields (a rebooked or cancelled
    # visit must win over our copy); local-only fields (notes) stay untouched.
    visit.client_id = client.id
    visit.starts_at = row.starts_at
    visit.service_name = row.service_name
    visit.status = row.status
    visit.price_pln = row.price_pln
    visit.staff_name = row.staff_name
    return False


def import_visit_rows(db: Session, rows: list[VisitRow]) -> ImportSummary:
    """Upsert parsed visit rows — the shared core of both the xlsx upload and the
    automatic pull (F5). Idempotent on booksy_ref."""
    cache: dict[str, Client] = {}
    clients_created = visits_created = visits_updated = 0
    for row in rows:
        client, created = _client_for(db, cache, row.client_name)
        clients_created += created
        if _upsert_visit(db, client, row):
            visits_created += 1
        else:
            visits_updated += 1

    summary = ImportSummary(
        visits_in_file=len(rows),
        clients_created=clients_created,
        visits_created=visits_created,
        visits_updated=visits_updated,
    )
    logger.info("booksy import: %s", summary.model_dump())
    return summary


@router.post("/booksy/visits", status_code=status.HTTP_200_OK)
def import_booksy_visits(
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File(description="Booksy Biz 'Lista wizyt' xlsx export")],
) -> ImportSummary:
    try:
        rows = parse_visits_report(file.file)
    except BooksyParseError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    return import_visit_rows(db, rows)


@router.put("/booksy/credentials", status_code=status.HTTP_204_NO_CONTENT)
def set_booksy_credentials(
    payload: BooksyCredentialsIn, db: Annotated[Session, Depends(get_db)]
) -> None:
    """Store/refresh the Booksy session credentials for the automatic pull. The
    access token rotates — the owner pastes a fresh one here, no redeploy."""
    row = db.scalars(select(BooksyCredential).order_by(BooksyCredential.id).limit(1)).first()
    if row is None:
        row = BooksyCredential(id=1)
        db.add(row)
    row.business_id = payload.business_id
    row.access_token = payload.access_token
    row.api_key = payload.api_key
    row.fingerprint = payload.fingerprint


@router.post("/booksy/pull", status_code=status.HTTP_200_OK)
def pull_booksy_visits(
    payload: PullRequest, db: Annotated[Session, Depends(get_db)]
) -> ImportSummary:
    """Download the visits report for a date range straight from Booksy and
    upsert it — automation of the manual xlsx upload."""
    from app.booksy_api import BooksyAuthError, pull_visits  # lazy: avoids import cycle

    try:
        return pull_visits(db, payload.report_key, payload.date_from, payload.date_till)
    except BooksyAuthError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    except BooksyParseError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
