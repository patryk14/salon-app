"""The staff portal's API (F6): everything scoped to the caller's OWN employee.

require_role("staff") gates the group; EmployeeDep (app.identity) resolves the
row scope from the token's sub — so a staff login can only ever read/write its
own schedule, revenue, hours and cash. Admin passes the role gate too but has
no employee link unless separately claimed; these endpoints are the employee's
self-view, not an admin tool.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.auth import UserDep, require_role
from app.commission import SettlementInput, compute_settlement
from app.derivation import (
    month_bounds,
    monthly_booksy_services,
    monthly_cash,
    monthly_hours,
    monthly_notebook_services,
)
from app.identity import DbDep, EmployeeDep, account_for
from app.models import (
    Availability,
    Client,
    EmployeeAlias,
    LedgerEntry,
    NotebookEntry,
    StaffDocument,
    TimeOff,
    TimesheetEntry,
    Visit,
)
from app.routers.settlement import _scheme_for
from app.routers.worklog import _norm_service
from app.schemas import (
    AvailabilityCreate,
    AvailabilityOut,
    MeCashCreate,
    MeCommissionOut,
    MeLink,
    MeNotebookCreate,
    MeRevenueOut,
    MeTimesheetCreate,
    StaffDocumentOut,
    TimeOffCreate,
    TimeOffOut,
    TimesheetOut,
    VisitBrowseOut,
)

MonthQuery = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]

me = APIRouter(prefix="/me", tags=["staff-portal"], dependencies=[require_role("staff")])


def _role_of(user: UserDep) -> str:
    if "admin" in user.groups:
        return "admin"
    if "staff" in user.groups:
        return "staff"
    return "client"


@me.get("")
def whoami(user: UserDep, db: DbDep) -> MeLink:
    """The caller's link state. `linked` is false until an invite is claimed —
    this endpoint must NOT require a link (it's what drives the claim box)."""
    account = account_for(db, user.sub)
    role = _role_of(user)
    if account is None or account.employee is None:
        return MeLink(linked=False, role=role)
    emp = account.employee
    return MeLink(
        linked=True,
        role=role,
        employee_id=emp.id,
        display_name=emp.display_name,
        fte_factor=emp.fte_factor,
        pay_type=emp.pay_type,
        is_active=emp.is_active,
    )


@me.get("/visits")
def my_visits(emp: EmployeeDep, db: DbDep, month: MonthQuery) -> list[VisitBrowseOut]:
    """My own schedule for the month — Booksy visits credited to me via my
    aliases. Newest first."""
    start, end = month_bounds(month)
    aliases = select(EmployeeAlias.alias).where(EmployeeAlias.employee_id == emp.id)
    name = Client.first_name + " " + Client.last_name
    rows = db.execute(
        select(Visit, name.label("client_name"))
        .join(Client, Visit.client_id == Client.id)
        .where(Visit.staff_name.in_(aliases), Visit.starts_at >= start, Visit.starts_at < end)
        .order_by(Visit.starts_at.desc())
    ).all()
    return [
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


@me.get("/revenue")
def my_revenue(emp: EmployeeDep, db: DbDep, month: MonthQuery) -> MeRevenueOut:
    """My merged service revenue for the month across the three sources."""
    booksy = monthly_booksy_services(db, emp.id, month)
    cash = monthly_cash(db, emp.id, month)
    notebook = monthly_notebook_services(db, emp.id, month)
    return MeRevenueOut(
        year_month=month,
        booksy_services=booksy,
        cash_services=cash,
        notebook_services=notebook,
        services_total=booksy + cash + notebook,
    )


@me.get("/commission")
def my_commission(emp: EmployeeDep, db: DbDep, month: MonthQuery) -> MeCommissionOut:
    """A live commission preview from my daily sources — not a closed line."""
    inp = SettlementInput(
        booksy_services=monthly_booksy_services(db, emp.id, month),
        cash_services=monthly_cash(db, emp.id, month),
        notebook_services=monthly_notebook_services(db, emp.id, month),
        hours=monthly_hours(db, emp.id, month),
    )
    result = compute_settlement(inp, _scheme_for(emp))
    return MeCommissionOut(
        year_month=month,
        services_base=result.services_base,
        services_rate=result.services_rate,
        services_commission=result.services_commission,
        sales_commission=result.sales_commission,
        hours=inp.hours,
        hours_pay=result.hours_pay,
        total_payout=result.total_payout,
    )


@me.get("/hours")
def my_hours(emp: EmployeeDep, db: DbDep, month: MonthQuery) -> list[TimesheetOut]:
    start, end = month_bounds(month)
    rows = db.scalars(
        select(TimesheetEntry)
        .where(
            TimesheetEntry.employee_id == emp.id,
            TimesheetEntry.work_date >= start,
            TimesheetEntry.work_date < end,
        )
        .order_by(TimesheetEntry.work_date)
    ).all()
    return [TimesheetOut.model_validate(r) for r in rows]


@me.post("/hours", status_code=status.HTTP_201_CREATED)
def log_my_hours(payload: MeTimesheetCreate, emp: EmployeeDep, db: DbDep) -> TimesheetOut:
    """Log my own hours (one row per day, upsert). employee_id is the token's,
    never the body's — I can only log for myself."""
    row = db.scalar(
        select(TimesheetEntry).where(
            TimesheetEntry.employee_id == emp.id, TimesheetEntry.work_date == payload.work_date
        )
    )
    if row is None:
        row = TimesheetEntry(employee_id=emp.id, work_date=payload.work_date)
        db.add(row)
    row.hours = payload.hours
    row.note = payload.note
    db.flush()
    return TimesheetOut.model_validate(row)


@me.post("/cash", status_code=status.HTTP_201_CREATED)
def log_my_cash(payload: MeCashCreate, emp: EmployeeDep, db: DbDep):
    """Record my own cash entry for a service (credited to me)."""
    row = LedgerEntry(
        employee_id=emp.id,
        entry_date=payload.entry_date,
        service_name=_norm_service(payload.service_name),
        amount_pln=payload.amount_pln,
        note=payload.note,
    )
    db.add(row)
    db.flush()
    return {"id": row.id, "amount_pln": str(row.amount_pln)}


# ---------------------------------------------------------- my documents (Day 1)
@me.get("/documents")
def my_documents(emp: EmployeeDep, db: DbDep) -> list[StaffDocumentOut]:
    """My own employment/RODO documents (read-only — the admin manages them)."""
    rows = db.scalars(
        select(StaffDocument)
        .where(StaffDocument.employee_id == emp.id)
        .order_by(StaffDocument.valid_until.is_(None), StaffDocument.valid_until)
    ).all()
    return [StaffDocumentOut.model_validate(d) for d in rows]


# ------------------------------------------------ my availability + time off (Day 1)
@me.get("/availability")
def my_availability(emp: EmployeeDep, db: DbDep, month: MonthQuery) -> list[AvailabilityOut]:
    start, end = month_bounds(month)
    rows = db.scalars(
        select(Availability)
        .where(
            Availability.employee_id == emp.id,
            Availability.work_date >= start,
            Availability.work_date < end,
        )
        .order_by(Availability.work_date)
    ).all()
    return [AvailabilityOut.model_validate(a) for a in rows]


@me.post("/availability", status_code=status.HTTP_201_CREATED)
def set_my_availability(
    payload: AvailabilityCreate, emp: EmployeeDep, db: DbDep
) -> AvailabilityOut:
    """Declare a day I can work (one row per day — re-posting overwrites)."""
    row = db.scalar(
        select(Availability).where(
            Availability.employee_id == emp.id, Availability.work_date == payload.work_date
        )
    )
    if row is None:
        row = Availability(employee_id=emp.id, work_date=payload.work_date)
        db.add(row)
    row.from_time = payload.from_time
    row.to_time = payload.to_time
    row.note = payload.note
    db.flush()
    return AvailabilityOut.model_validate(row)


@me.delete("/availability/{avail_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_availability(avail_id: int, emp: EmployeeDep, db: DbDep) -> None:
    row = db.get(Availability, avail_id)
    if row is None or row.employee_id != emp.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    db.delete(row)


@me.get("/time-off")
def my_time_off(emp: EmployeeDep, db: DbDep) -> list[TimeOffOut]:
    rows = db.scalars(
        select(TimeOff).where(TimeOff.employee_id == emp.id).order_by(TimeOff.start_date)
    ).all()
    return [TimeOffOut.model_validate(t) for t in rows]


@me.post("/time-off", status_code=status.HTTP_201_CREATED)
def request_my_time_off(payload: TimeOffCreate, emp: EmployeeDep, db: DbDep) -> TimeOffOut:
    if payload.end_date < payload.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="end_date before start_date")
    row = TimeOff(
        employee_id=emp.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        kind=payload.kind,
        note=payload.note,
    )
    db.add(row)
    db.flush()
    return TimeOffOut.model_validate(row)


@me.delete("/time-off/{off_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_time_off(off_id: int, emp: EmployeeDep, db: DbDep) -> None:
    row = db.get(TimeOff, off_id)
    if row is None or row.employee_id != emp.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    db.delete(row)


@me.post("/notebook", status_code=status.HTTP_201_CREATED)
def log_my_notebook(payload: MeNotebookCreate, emp: EmployeeDep, db: DbDep):
    """Record my own prepaid (package/voucher) visit — credits commission to me.
    The anti-fraud reconciliation (admin readiness) still requires a matching
    Booksy visit for me on that day, so this is not a free-money entry."""
    row = NotebookEntry(
        employee_id=emp.id,
        entry_date=payload.entry_date,
        service_name=_norm_service(payload.service_name),
        amount_pln=payload.amount_pln,
        note=payload.note,
    )
    db.add(row)
    db.flush()
    return {"id": row.id, "amount_pln": str(row.amount_pln)}
