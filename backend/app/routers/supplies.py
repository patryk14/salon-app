"""Internal supply / shopping list (Day 1) — things to buy for the salon.

NOT the customer shop (F11). A shared salon list: any staff or admin adds
items, marks them bought, edits or removes them. Deliberately not row-scoped —
everyone sees the same list.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import UserDep, require_role
from app.deps import get_db
from app.models import SupplyItem, utcnow
from app.schemas import SupplyItemCreate, SupplyItemOut, SupplyItemUpdate

DbDep = Annotated[Session, Depends(get_db)]

# Staff + admin (admin passes the staff gate).
supplies = APIRouter(prefix="/supplies", tags=["supplies"], dependencies=[require_role("staff")])


@supplies.get("")
def list_supplies(db: DbDep) -> list[SupplyItemOut]:
    """To-buy first (newest last so the list reads top-down), then bought."""
    rows = db.scalars(
        select(SupplyItem).order_by(SupplyItem.status.desc(), SupplyItem.created_at)
    ).all()
    return [SupplyItemOut.model_validate(r) for r in rows]


@supplies.post("", status_code=status.HTTP_201_CREATED)
def add_supply(payload: SupplyItemCreate, user: UserDep, db: DbDep) -> SupplyItemOut:
    row = SupplyItem(name=payload.name.strip(), note=payload.note, created_by=user.username)
    db.add(row)
    db.flush()
    return SupplyItemOut.model_validate(row)


@supplies.patch("/{item_id}")
def update_supply(item_id: int, payload: SupplyItemUpdate, db: DbDep) -> SupplyItemOut:
    row = db.get(SupplyItem, item_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="item not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        row.name = data["name"].strip()
    if "note" in data:
        row.note = data["note"]
    if "status" in data and data["status"]:
        row.status = data["status"]
        # Stamp when it was bought so "bought" entries can be shown/sorted by time.
        row.bought_at = utcnow() if data["status"] == "bought" else None
    db.flush()
    return SupplyItemOut.model_validate(row)


@supplies.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supply(item_id: int, db: DbDep) -> None:
    row = db.get(SupplyItem, item_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="item not found")
    db.delete(row)
