"""Client packages (synced from Booksy) + manual correction.

Browsing is read-only over the Booksy-synced snapshot. On top of that the owner
can MARK a treatment used by hand when Booksy missed it (a late cancel counts as
used, ruling #16) and ASSIGN the performer to redemptions Booksy couldn't match —
both carry a who+when audit trail. A manual redemption with a performer credits
commission exactly like a synced one (the settlement derivation sums them);
without a performer it is a pure count correction.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import UserDep, require_role
from app.deps import get_db
from app.models import Employee, Package, PackageRedemption
from app.schemas import PackageOut, PackageRedeemIn, RedemptionAssignIn, RedemptionOut

DbDep = Annotated[Session, Depends(get_db)]

packages = APIRouter(prefix="/packages", tags=["packages"], dependencies=[require_role("admin")])


def _status(p: Package, effective_remaining: int, today: date) -> str:
    if effective_remaining <= 0:
        return "used_up"
    if p.valid_until and p.valid_until < today:
        return "expired"
    return "active"


def _redemption_out(db: Session, r: PackageRedemption) -> RedemptionOut:
    pkg = db.get(Package, r.package_id) if r.package_id else None
    emp = db.get(Employee, r.employee_id) if r.employee_id else None
    return RedemptionOut(
        id=r.id,
        package_id=r.package_id,
        package_name=pkg.name if pkg else None,
        client_name=r.client_name,
        redemption_date=r.redemption_date,
        value=r.value,
        employee_id=r.employee_id,
        employee_name=emp.display_name if emp else None,
        source=r.source,
        note=r.note,
        created_by=r.created_by,
        assigned_by=r.assigned_by,
        created_at=r.created_at,
    )


@packages.get("")
def list_packages(db: DbDep) -> list[PackageOut]:
    """Active first (soonest to expire), then used-up/expired. 'effective_remaining'
    subtracts manual redemptions Booksy doesn't yet know about."""
    manual = dict(
        db.execute(
            select(PackageRedemption.package_id, func.count())
            .where(PackageRedemption.source == "manual", PackageRedemption.package_id.is_not(None))
            .group_by(PackageRedemption.package_id)
        ).all()
    )
    today = date.today()
    out: list[PackageOut] = []
    for p in db.scalars(select(Package)).all():
        mu = int(manual.get(p.id, 0))
        effective = max(0, p.remaining - mu)
        out.append(
            PackageOut(
                id=p.id,
                client_name=p.client_name,
                name=p.name,
                total_value=p.total_value,
                total_treatments=p.total_treatments,
                remaining=p.remaining,
                used=p.total_treatments - p.remaining,
                value_per_treatment=(
                    (p.total_value / p.total_treatments).quantize(Decimal("0.01"))
                    if p.total_treatments
                    else Decimal("0")
                ),
                valid_until=p.valid_until,
                status=_status(p, effective, today),
                manual_used=mu,
                effective_remaining=effective,
            )
        )
    rank = {"active": 0, "used_up": 1, "expired": 2}
    out.sort(key=lambda x: (rank[x.status], x.valid_until or date.max))
    return out


@packages.post("/{package_id}/redeem")
def redeem_package(
    package_id: int, payload: PackageRedeemIn, user: UserDep, db: DbDep
) -> RedemptionOut:
    """Mark one treatment used manually (Booksy missed it). Optional performer →
    commission; omit for a pure count fix. Audited (created_by / assigned_by)."""
    p = db.get(Package, package_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego pakietu.")
    if payload.employee_id is not None and db.get(Employee, payload.employee_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej pracownicy.")
    value = (
        (p.total_value / p.total_treatments).quantize(Decimal("0.01"))
        if p.total_treatments
        else Decimal("0")
    )
    r = PackageRedemption(
        booksy_ref=None,
        package_id=p.id,
        employee_id=payload.employee_id,
        client_name=p.client_name,
        redemption_date=payload.redemption_date or date.today(),
        value=value,
        source="manual",
        note=payload.note,
        created_by=user.username,
        assigned_by=user.username if payload.employee_id is not None else None,
    )
    db.add(r)
    db.flush()
    return _redemption_out(db, r)


@packages.get("/redemptions/unmatched")
def unmatched_redemptions(db: DbDep) -> list[RedemptionOut]:
    """Redemptions needing a performer (or a package link), for manual assignment.
    Zero-value rows are skipped: those are Booksy till artifacts — a package rung
    up on the register with no reservation ('Klient bez rezerwacji'), so there's
    no client to match and nothing to pay. They stay in the DB but out of the
    queue."""
    rows = db.scalars(
        select(PackageRedemption)
        .where(
            (PackageRedemption.employee_id.is_(None) | PackageRedemption.package_id.is_(None))
            & (PackageRedemption.value > 0)
        )
        .order_by(PackageRedemption.redemption_date.desc())
    ).all()
    return [_redemption_out(db, r) for r in rows]


@packages.put("/redemptions/{redemption_id}")
def assign_redemption(
    redemption_id: int, payload: RedemptionAssignIn, user: UserDep, db: DbDep
) -> RedemptionOut:
    """Set the performer (and/or link a package) for a redemption. Audited."""
    r = db.get(PackageRedemption, redemption_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej realizacji.")
    if payload.clear_employee:
        r.employee_id = None
    elif payload.employee_id is not None:
        if db.get(Employee, payload.employee_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej pracownicy.")
        r.employee_id = payload.employee_id
    if payload.package_id is not None:
        pkg = db.get(Package, payload.package_id)
        if pkg is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego pakietu.")
        r.package_id = payload.package_id
        if not r.client_name:
            r.client_name = pkg.client_name
    if payload.note is not None:
        r.note = payload.note
    r.assigned_by = user.username
    db.flush()
    return _redemption_out(db, r)


@packages.delete("/redemptions/{redemption_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_redemption(redemption_id: int, db: DbDep) -> None:
    r = db.get(PackageRedemption, redemption_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej realizacji.")
    db.delete(r)
    db.flush()
