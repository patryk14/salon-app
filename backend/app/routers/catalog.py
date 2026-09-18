"""Service catalog + rebooking (F8) — admin.

The catalog is synced from the service names on completed visits. The owner sets
a rebook interval (+ optional recommendation) on the ones that matter; from that
the client portal suggests her next visit and this router lists who is due, so
the salon can reach out (email reminders come with SES later — F9).
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.deps import get_db
from app.models import Client, Service, Visit
from app.schemas import CatalogSyncSummary, DueRebook, ServiceOut, ServiceUpdate

DbDep = Annotated[Session, Depends(get_db)]

catalog = APIRouter(prefix="/catalog", tags=["catalog"], dependencies=[require_role("admin")])

# Don't nag about clients who lapsed long ago — only surface recently-due ones.
_DUE_LOOKBACK_DAYS = 90


def _visit_counts(db: Session) -> dict[str, int]:
    return dict(
        db.execute(
            select(Visit.service_name, func.count())
            .where(Visit.status == "completed")
            .group_by(Visit.service_name)
        ).all()
    )


@catalog.get("")
def list_services(db: DbDep) -> list[ServiceOut]:
    """The catalog, most-used first (so the owner curates the top services)."""
    counts = _visit_counts(db)
    rows = db.scalars(select(Service)).all()
    out = [
        ServiceOut(
            id=s.id,
            name=s.name,
            visit_count=int(counts.get(s.name, 0)),
            rebook_interval_days=s.rebook_interval_days,
            recommendation=s.recommendation,
            active=s.active,
        )
        for s in rows
    ]
    out.sort(key=lambda x: (-x.visit_count, x.name))
    return out


@catalog.post("/sync")
def sync_catalog(db: DbDep) -> CatalogSyncSummary:
    """Add any new completed-visit service names to the catalog. Idempotent;
    keeps existing intervals/recommendations."""
    existing = set(db.scalars(select(Service.name)).all())
    names = db.scalars(
        select(distinct(Visit.service_name)).where(
            Visit.status == "completed", Visit.service_name.is_not(None)
        )
    ).all()
    created = 0
    for name in names:
        if name and name not in existing:
            db.add(Service(name=name))
            existing.add(name)
            created += 1
    db.flush()
    return CatalogSyncSummary(total=len(existing), created=created)


@catalog.patch("/{service_id}")
def update_service(service_id: int, payload: ServiceUpdate, db: DbDep) -> ServiceOut:
    s = db.get(Service, service_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej usługi.")
    if payload.clear_interval:
        s.rebook_interval_days = None
    elif payload.rebook_interval_days is not None:
        s.rebook_interval_days = payload.rebook_interval_days
    if payload.recommendation is not None:
        s.recommendation = payload.recommendation
    if payload.active is not None:
        s.active = payload.active
    db.flush()
    counts = _visit_counts(db)
    return ServiceOut(
        id=s.id,
        name=s.name,
        visit_count=int(counts.get(s.name, 0)),
        rebook_interval_days=s.rebook_interval_days,
        recommendation=s.recommendation,
        active=s.active,
    )


@catalog.get("/due")
def due_rebookings(
    db: DbDep, within_days: Annotated[int, Query(ge=0, le=90)] = 14
) -> list[DueRebook]:
    """Clients whose next visit of a service is due (or overdue within the
    lookback) — for the salon to reach out. Computed in Python for portability."""
    intervals = {
        s.name: s.rebook_interval_days
        for s in db.scalars(
            select(Service).where(
                Service.active.is_(True), Service.rebook_interval_days.is_not(None)
            )
        ).all()
    }
    if not intervals:
        return []
    last_visits = db.execute(
        select(Visit.client_id, Visit.service_name, func.max(Visit.starts_at))
        .where(Visit.status == "completed", Visit.service_name.in_(intervals))
        .group_by(Visit.client_id, Visit.service_name)
    ).all()

    today = date.today()
    horizon = today + timedelta(days=within_days)
    floor = today - timedelta(days=_DUE_LOOKBACK_DAYS)
    hits: list[tuple[int, str, date, date]] = []
    for client_id, service, last_dt in last_visits:
        if client_id is None or last_dt is None:
            continue
        last = last_dt.date() if hasattr(last_dt, "date") else last_dt
        nxt = last + timedelta(days=intervals[service])
        if floor <= nxt <= horizon:
            hits.append((client_id, service, last, nxt))

    clients = {
        c.id: c for c in db.scalars(select(Client).where(Client.id.in_({h[0] for h in hits}))).all()
    }
    out = [
        DueRebook(
            client_id=cid,
            client_name=f"{clients[cid].first_name} {clients[cid].last_name}",
            phone=clients[cid].phone,
            service=service,
            last_visit=last,
            suggested_next=nxt,
        )
        for cid, service, last, nxt in hits
        if cid in clients
    ]
    out.sort(key=lambda x: x.suggested_next)
    return out
