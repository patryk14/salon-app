"""Timesheets and the cash ledger (F3) — the daily inputs the monthly
settlement is built from.

Admin-only for now (the owner enters everyone's numbers); staff self-entry of
their own hours/cash arrives with the staff portal (F6), when a logged-in
employee is row-scoped to their own employee_id.

The monthly rollups (sum of hours, sum of cash per employee) are always
COMPUTED from these rows, never stored — re-deriving a settlement line always
reflects the current entries, and the "dropped cash" bug class cannot recur.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.deps import get_db
from app.models import LedgerEntry, TimesheetEntry
from app.schemas import (
    LedgerCreate,
    LedgerOut,
    TimesheetCreate,
    TimesheetOut,
)

DbDep = Annotated[Session, Depends(get_db)]

timesheets = APIRouter(prefix="/timesheets", tags=["worklog"], dependencies=[require_role("admin")])
ledger = APIRouter(prefix="/ledger", tags=["worklog"], dependencies=[require_role("admin")])


def _month_bounds(year_month: str) -> tuple[date, date]:
    """First day of the month and first day of the next — a half-open range
    [start, end) that avoids month-length and leap-year edge cases."""
    year, month = (int(p) for p in year_month.split("-"))
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


# ------------------------------------------------------------------ timesheets
@timesheets.post("", status_code=status.HTTP_201_CREATED)
def upsert_timesheet(payload: TimesheetCreate, db: DbDep) -> TimesheetOut:
    """One row per (employee, day): re-posting the same day overwrites."""
    row = db.scalar(
        select(TimesheetEntry).where(
            TimesheetEntry.employee_id == payload.employee_id,
            TimesheetEntry.work_date == payload.work_date,
        )
    )
    if row is None:
        row = TimesheetEntry(employee_id=payload.employee_id, work_date=payload.work_date)
        db.add(row)
    row.hours = payload.hours
    row.note = payload.note
    db.flush()
    return TimesheetOut.model_validate(row)


@timesheets.get("")
def list_timesheets(
    db: DbDep,
    employee_id: int | None = None,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> list[TimesheetOut]:
    q = select(TimesheetEntry)
    if employee_id is not None:
        q = q.where(TimesheetEntry.employee_id == employee_id)
    if month is not None:
        start, end = _month_bounds(month)
        q = q.where(TimesheetEntry.work_date >= start, TimesheetEntry.work_date < end)
    rows = db.scalars(q.order_by(TimesheetEntry.work_date)).all()
    return [TimesheetOut.model_validate(r) for r in rows]


@timesheets.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_timesheet(entry_id: int, db: DbDep) -> None:
    if not db.get(TimesheetEntry, entry_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="entry not found")
    db.execute(delete(TimesheetEntry).where(TimesheetEntry.id == entry_id))


# ---------------------------------------------------------------------- ledger
@ledger.post("", status_code=status.HTTP_201_CREATED)
def add_ledger_entry(payload: LedgerCreate, db: DbDep) -> LedgerOut:
    row = LedgerEntry(**payload.model_dump())
    db.add(row)
    db.flush()
    return LedgerOut.model_validate(row)


@ledger.get("")
def list_ledger(
    db: DbDep,
    employee_id: int | None = None,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> list[LedgerOut]:
    q = select(LedgerEntry)
    if employee_id is not None:
        q = q.where(LedgerEntry.employee_id == employee_id)
    if month is not None:
        start, end = _month_bounds(month)
        q = q.where(LedgerEntry.entry_date >= start, LedgerEntry.entry_date < end)
    rows = db.scalars(q.order_by(LedgerEntry.entry_date)).all()
    return [LedgerOut.model_validate(r) for r in rows]


@ledger.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ledger_entry(entry_id: int, db: DbDep) -> None:
    if not db.get(LedgerEntry, entry_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="entry not found")
    db.execute(delete(LedgerEntry).where(LedgerEntry.id == entry_id))
