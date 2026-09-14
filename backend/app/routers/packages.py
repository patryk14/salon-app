"""Client packages (synced from Booksy) — the admin view of who holds what,
how many treatments are left and when it expires. Commission from redemptions
is wired in the settlement derivation; this router is read-only browsing.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.deps import get_db
from app.models import Package
from app.schemas import PackageOut

DbDep = Annotated[Session, Depends(get_db)]

packages = APIRouter(prefix="/packages", tags=["packages"], dependencies=[require_role("admin")])


def _status(p: Package, today: date) -> str:
    if p.remaining <= 0:
        return "used_up"
    if p.valid_until and p.valid_until < today:
        return "expired"
    return "active"


@packages.get("")
def list_packages(db: DbDep) -> list[PackageOut]:
    """Active first (soonest to expire), then used-up/expired."""
    rows = db.scalars(select(Package)).all()
    today = date.today()
    out = [
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
            status=_status(p, today),
        )
        for p in rows
    ]
    # active first, then by soonest expiry
    rank = {"active": 0, "used_up": 1, "expired": 2}
    out.sort(key=lambda x: (rank[x.status], x.valid_until or date.max))
    return out
