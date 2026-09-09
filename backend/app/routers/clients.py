"""Client profiles + their visits.

Gated to staff+admin (F0): the front desk needs client profiles day-to-day.
Row-scoped CLIENT access (a client seeing only herself) arrives with the
client portal slice — these endpoints stay staff-facing.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.deps import get_db
from app.derivation import month_bounds
from app.models import Client, Visit
from app.schemas import (
    ClientCreate,
    ClientOut,
    ClientUpdate,
    Page,
    VisitBrowseOut,
    VisitCreate,
    VisitOut,
    VisitUpdate,
)

router = APIRouter(prefix="/clients", tags=["clients"], dependencies=[require_role("staff")])
visits_router = APIRouter(prefix="/visits", tags=["visits"], dependencies=[require_role("staff")])

DbDep = Annotated[Session, Depends(get_db)]


def _get_client_or_404(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="client not found")
    return client


@router.get("")
def list_clients(
    db: DbDep,
    q: str | None = Query(default=None, max_length=100, description="search in name/phone"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ClientOut]:
    query = select(Client)
    if q:
        pattern = f"%{q}%"
        query = query.where(
            or_(
                Client.first_name.ilike(pattern),
                Client.last_name.ilike(pattern),
                Client.phone.ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(Client.last_name, Client.first_name).limit(limit).offset(offset)
    ).all()
    return Page[ClientOut](
        items=[ClientOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate, db: DbDep) -> ClientOut:
    client = Client(**payload.model_dump())
    db.add(client)
    db.flush()  # assigns the id within the request's transaction
    return ClientOut.model_validate(client)


@router.get("/{client_id}")
def get_client(client_id: int, db: DbDep) -> ClientOut:
    return ClientOut.model_validate(_get_client_or_404(db, client_id))


@router.patch("/{client_id}")
def update_client(client_id: int, payload: ClientUpdate, db: DbDep) -> ClientOut:
    client = _get_client_or_404(db, client_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    db.flush()
    return ClientOut.model_validate(client)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(client_id: int, db: DbDep) -> None:
    """GDPR erasure path: cascades to visits and photo ROWS. S3 objects behind
    those photos are handled in the photos slice (delete must cover both)."""
    db.delete(_get_client_or_404(db, client_id))


@router.get("/{client_id}/visits")
def list_client_visits(
    client_id: int,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[VisitOut]:
    _get_client_or_404(db, client_id)
    base = select(Visit).where(Visit.client_id == client_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Visit.starts_at.desc()).limit(limit).offset(offset)).all()
    return Page[VisitOut](
        items=[VisitOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post("/{client_id}/visits", status_code=status.HTTP_201_CREATED)
def create_visit(client_id: int, payload: VisitCreate, db: DbDep) -> VisitOut:
    _get_client_or_404(db, client_id)
    visit = Visit(client_id=client_id, **payload.model_dump())
    db.add(visit)
    db.flush()
    return VisitOut.model_validate(visit)


@visits_router.get("")
def list_visits(
    db: DbDep,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
    q: str | None = Query(default=None, max_length=100, description="search client/service/staff"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[VisitBrowseOut]:
    """Browse the imported/pulled visits, newest first, with the client name."""
    # `+` on string columns → the `||` concat operator on both SQLite and Postgres
    # (func.concat would emit CONCAT(), which SQLite lacks).
    name = Client.first_name + " " + Client.last_name
    base = select(Visit, name.label("client_name")).join(Client, Visit.client_id == Client.id)
    if month:
        # date bounds, NOT f-string dates: comparing a TIMESTAMP column to a
        # VARCHAR works on SQLite but 500s on Postgres (operator type mismatch).
        start, end = month_bounds(month)
        base = base.where(Visit.starts_at >= start, Visit.starts_at < end)
    if q:
        pattern = f"%{q}%"
        base = base.where(
            or_(
                name.ilike(pattern),
                Visit.service_name.ilike(pattern),
                Visit.staff_name.ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(Visit.starts_at.desc()).limit(limit).offset(offset)).all()
    items = [
        VisitBrowseOut(
            id=v.id,
            starts_at=v.starts_at,
            client_name=client_name,
            service_name=v.service_name,
            staff_name=v.staff_name,
            price_pln=v.price_pln,
            status=v.status,
        )
        for v, client_name in rows
    ]
    return Page[VisitBrowseOut](items=items, total=total, limit=limit, offset=offset)


@visits_router.patch("/{visit_id}")
def update_visit(visit_id: int, payload: VisitUpdate, db: DbDep) -> VisitOut:
    visit = db.get(Visit, visit_id)
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="visit not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(visit, field, value)
    db.flush()
    return VisitOut.model_validate(visit)


@visits_router.delete("/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_visit(visit_id: int, db: DbDep) -> None:
    visit = db.get(Visit, visit_id)
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="visit not found")
    db.delete(visit)
