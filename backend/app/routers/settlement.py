"""Employees, the commission decision log, and monthly settlement.

Admin-only (the owner). The money math lives in app.commission (pure, tested
against the real sheets); this router is the persistence + workflow around it:
enter each employee's numbers into a DRAFT period, recompute on every edit,
then CLOSE to freeze — a closed line keeps the exact scheme it was computed
against, so a later rule change (e.g. the 12% bracket) never rewrites payroll.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import UserDep, require_role
from app.commission import (
    BASE_SERVICES_BRACKETS,
    CommissionScheme,
    SettlementInput,
    compute_settlement,
)
from app.deps import get_db
from app.models import (
    CommissionDecision,
    Employee,
    EmployeeAlias,
    SettlementLine,
    SettlementPeriod,
    utcnow,
)
from app.schemas import (
    DecisionCreate,
    DecisionOut,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    PeriodCreate,
    SettlementInputIn,
    SettlementLineOut,
    SettlementPeriodOut,
)

DbDep = Annotated[Session, Depends(get_db)]

# Everything here is the owner's, so gate the whole router at the admin role.
employees = APIRouter(prefix="/employees", tags=["employees"], dependencies=[require_role("admin")])
settlement = APIRouter(
    prefix="/settlement", tags=["settlement"], dependencies=[require_role("admin")]
)
decisions = APIRouter(
    prefix="/commission/decisions", tags=["commission"], dependencies=[require_role("admin")]
)


def _scheme_for(emp: Employee) -> CommissionScheme:
    """The pay scheme an employee is currently on — the base bracket table
    scaled by their FTE, plus their hourly rate."""
    return CommissionScheme(
        fte_factor=emp.fte_factor,
        services_brackets=tuple(BASE_SERVICES_BRACKETS),
        hourly_rate=emp.hourly_rate,
    )


def _freeze(scheme: CommissionScheme) -> dict:
    """Serialize the scheme to JSON (Decimals as strings) for the frozen
    snapshot stored on a settlement line."""
    return {
        "fte_factor": str(scheme.fte_factor),
        "hourly_rate": str(scheme.hourly_rate),
        "sales_threshold": str(scheme.sales_threshold),
        "sales_rate": str(scheme.sales_rate),
        "services_brackets": [[str(b), str(r)] for b, r in scheme.services_brackets],
    }


# ------------------------------------------------------------------- employees
@employees.get("")
def list_employees(db: DbDep) -> list[EmployeeOut]:
    rows = db.scalars(select(Employee).order_by(Employee.display_name)).all()
    return [EmployeeOut.model_validate(e) for e in rows]


@employees.post("", status_code=status.HTTP_201_CREATED)
def create_employee(payload: EmployeeCreate, db: DbDep) -> EmployeeOut:
    data = payload.model_dump(exclude={"aliases"})
    emp = Employee(**data)
    emp.aliases = [EmployeeAlias(alias=a) for a in payload.aliases]
    db.add(emp)
    db.flush()
    return EmployeeOut.model_validate(emp)


@employees.patch("/{employee_id}")
def update_employee(employee_id: int, payload: EmployeeUpdate, db: DbDep) -> EmployeeOut:
    emp = db.get(Employee, employee_id)
    if emp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="employee not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(emp, field, value)
    db.flush()
    return EmployeeOut.model_validate(emp)


# ------------------------------------------------------------- decision log
@decisions.get("")
def list_decisions(db: DbDep) -> list[DecisionOut]:
    rows = db.scalars(select(CommissionDecision).order_by(CommissionDecision.decided_on)).all()
    return [DecisionOut.model_validate(d) for d in rows]


@decisions.post("", status_code=status.HTTP_201_CREATED)
def add_decision(payload: DecisionCreate, db: DbDep) -> DecisionOut:
    d = CommissionDecision(**payload.model_dump())
    db.add(d)
    db.flush()
    return DecisionOut.model_validate(d)


# ------------------------------------------------------------------ settlement
def _get_period(db: Session, year_month: str) -> SettlementPeriod:
    period = db.scalar(
        select(SettlementPeriod)
        .where(SettlementPeriod.year_month == year_month)
        .options(selectinload(SettlementPeriod.lines))
    )
    if period is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="period not found")
    return period


@settlement.get("/periods")
def list_periods(db: DbDep) -> list[str]:
    return list(
        db.scalars(select(SettlementPeriod.year_month).order_by(SettlementPeriod.year_month.desc()))
    )


@settlement.post("/periods", status_code=status.HTTP_201_CREATED)
def create_period(payload: PeriodCreate, db: DbDep) -> SettlementPeriodOut:
    if db.scalar(select(SettlementPeriod).where(SettlementPeriod.year_month == payload.year_month)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="period already exists")
    period = SettlementPeriod(year_month=payload.year_month)
    db.add(period)
    db.flush()
    return SettlementPeriodOut.model_validate(period)


@settlement.get("/periods/{year_month}")
def get_period(year_month: str, db: DbDep) -> SettlementPeriodOut:
    return SettlementPeriodOut.model_validate(_get_period(db, year_month))


@settlement.put("/periods/{year_month}/lines/{employee_id}")
def upsert_line(
    year_month: str, employee_id: int, payload: SettlementInputIn, db: DbDep
) -> SettlementLineOut:
    period = _get_period(db, year_month)
    if period.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="period is closed; reopen is not supported"
        )
    emp = db.get(Employee, employee_id)
    if emp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="employee not found")

    scheme = _scheme_for(emp)
    inp = SettlementInput(
        booksy_services=payload.booksy_services,
        booksy_sales=payload.booksy_sales,
        notebook_services=payload.notebook_services,
        cash_services=payload.cash_services,
        notebook_sales=payload.notebook_sales,
        cash_sales=payload.cash_sales,
        hours=payload.hours,
    )
    result = compute_settlement(inp, scheme)

    line = db.scalar(
        select(SettlementLine).where(
            SettlementLine.period_id == period.id, SettlementLine.employee_id == employee_id
        )
    )
    if line is None:
        line = SettlementLine(period_id=period.id, employee_id=employee_id)
        db.add(line)

    # inputs
    for f in (
        "booksy_services",
        "booksy_sales",
        "notebook_services",
        "cash_services",
        "notebook_sales",
        "cash_sales",
        "hours",
    ):
        setattr(line, f, getattr(payload, f))
    # frozen scheme
    line.frozen_fte_factor = scheme.fte_factor
    line.frozen_hourly_rate = scheme.hourly_rate
    line.frozen_scheme = _freeze(scheme)
    # outputs
    line.services_base = result.services_base
    line.sales_base = result.sales_base
    line.services_rate = result.services_rate
    line.services_commission = result.services_commission
    line.sales_commission = result.sales_commission
    line.hours_pay = result.hours_pay
    line.total_payout = result.total_payout
    # override (an admin's final say over the computed total)
    line.override_total = payload.override_total
    line.override_reason = payload.override_reason

    db.flush()
    return SettlementLineOut.model_validate(line)


@settlement.post("/periods/{year_month}/lines/{employee_id}/derive")
def derive_line_from_sources(year_month: str, employee_id: int, db: DbDep) -> SettlementLineOut:
    """Pre-fill this line's hours + cash_services from the month's timesheets and
    ledger (F3), then recompute. Booksy/notebook figures stay as entered — those
    come from the Booksy import (F5) and the notebook (F4), not this."""
    from app.routers.worklog import monthly_cash, monthly_hours

    period = _get_period(db, year_month)
    if period.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="period is closed")
    emp = db.get(Employee, employee_id)
    if emp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="employee not found")

    line = db.scalar(
        select(SettlementLine).where(
            SettlementLine.period_id == period.id, SettlementLine.employee_id == employee_id
        )
    )
    payload = SettlementInputIn(
        booksy_services=line.booksy_services if line else Decimal("0"),
        booksy_sales=line.booksy_sales if line else Decimal("0"),
        notebook_services=line.notebook_services if line else Decimal("0"),
        notebook_sales=line.notebook_sales if line else Decimal("0"),
        cash_sales=line.cash_sales if line else Decimal("0"),
        override_total=line.override_total if line else None,
        override_reason=line.override_reason if line else None,
        # derived from F3 sources:
        cash_services=monthly_cash(db, employee_id, year_month),
        hours=monthly_hours(db, employee_id, year_month),
    )
    return upsert_line(year_month, employee_id, payload, db)


@settlement.post("/periods/{year_month}/close")
def close_period(year_month: str, user: UserDep, db: DbDep) -> SettlementPeriodOut:
    period = _get_period(db, year_month)
    if period.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="period already closed")
    if not period.lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no lines to close")
    period.status = "closed"
    period.closed_at = utcnow()
    period.closed_by = user.username
    db.flush()
    return SettlementPeriodOut.model_validate(period)


def payout_of(line: SettlementLine) -> Decimal:
    """The amount actually paid: an admin override wins over the computed total."""
    return line.override_total if line.override_total is not None else line.total_payout
