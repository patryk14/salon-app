"""Booksy xlsx import.

Idempotent by design: `booksy_ref` (Booksy reservation id) is unique in the
visits table, so re-uploading the same or an overlapping report UPDATES
existing rows instead of duplicating them. Clients are matched by display name
(the only identity Booksy reports expose) and created on first sight.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.booksy import BooksyParseError, VisitRow, parse_visits_report, split_name
from app.deps import get_db
from app.models import Client, Visit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])


class ImportSummary(BaseModel):
    visits_in_file: int
    clients_created: int
    visits_created: int
    visits_updated: int


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


@router.post("/booksy/visits", status_code=status.HTTP_200_OK)
def import_booksy_visits(
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File(description="Booksy Biz 'Lista wizyt' xlsx export")],
) -> ImportSummary:
    try:
        rows = parse_visits_report(file.file)
    except BooksyParseError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

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
