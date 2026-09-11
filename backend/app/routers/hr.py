"""Admin-side HR (Day 1): staff documents (with expiry), and the salon-wide
view of availability + time-off (approve). Staff self-service equivalents live
under /me/* (app.routers.me); this file is the owner's overview.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.deps import get_db
from app.derivation import month_bounds
from app.models import Availability, Employee, StaffDocument, TimeOff
from app.schemas import (
    AvailabilityOut,
    StaffDocumentCreate,
    StaffDocumentOut,
    TimeOffOut,
    TimeOffUpdate,
)

DbDep = Annotated[Session, Depends(get_db)]
MonthQuery = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]

documents = APIRouter(prefix="/staff-documents", tags=["hr"], dependencies=[require_role("admin")])
scheduling = APIRouter(prefix="/scheduling", tags=["hr"], dependencies=[require_role("admin")])


# ------------------------------------------------------------ staff documents
@documents.get("")
def list_documents(db: DbDep, employee_id: int | None = None) -> list[StaffDocumentOut]:
    q = select(StaffDocument)
    if employee_id is not None:
        q = q.where(StaffDocument.employee_id == employee_id)
    # NULLs (no expiry) last, then soonest-expiring first.
    q = q.order_by(StaffDocument.valid_until.is_(None), StaffDocument.valid_until)
    return [StaffDocumentOut.model_validate(d) for d in db.scalars(q).all()]


@documents.post("", status_code=status.HTTP_201_CREATED)
def add_document(payload: StaffDocumentCreate, db: DbDep) -> StaffDocumentOut:
    if db.get(Employee, payload.employee_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="employee not found")
    row = StaffDocument(**payload.model_dump())
    db.add(row)
    db.flush()
    return StaffDocumentOut.model_validate(row)


@documents.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: int, db: DbDep) -> None:
    row = db.get(StaffDocument, doc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    db.delete(row)


# ----------------------------------------------- availability + time off (all)
@scheduling.get("/availability")
def all_availability(db: DbDep, month: MonthQuery = None) -> list[AvailabilityOut]:
    q = select(Availability)
    if month:
        start, end = month_bounds(month)
        q = q.where(Availability.work_date >= start, Availability.work_date < end)
    rows = db.scalars(q.order_by(Availability.work_date, Availability.employee_id)).all()
    return [AvailabilityOut.model_validate(a) for a in rows]


@scheduling.get("/time-off")
def all_time_off(
    db: DbDep, status_filter: str | None = Query(default=None, alias="status")
) -> list[TimeOffOut]:
    q = select(TimeOff)
    if status_filter:
        q = q.where(TimeOff.status == status_filter)
    rows = db.scalars(q.order_by(TimeOff.start_date)).all()
    return [TimeOffOut.model_validate(t) for t in rows]


@scheduling.patch("/time-off/{off_id}")
def set_time_off_status(off_id: int, payload: TimeOffUpdate, db: DbDep) -> TimeOffOut:
    row = db.get(TimeOff, off_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="time-off not found")
    row.status = payload.status
    db.flush()
    return TimeOffOut.model_validate(row)
