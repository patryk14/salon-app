"""Invites — how a Cognito login gets bound to an employee (F6).

No self-signup: the admin creates a Cognito staff user (in the `staff` group)
and an invite for the matching Employee row, then hands over the short code.
The staff logs in and claims the code once; the claim binds sub→employee
ATOMICALLY (a conditional UPDATE, so two racing claims can't both win). Client
invites (F7) reuse the same table with a client_id target.
"""

import secrets
from datetime import UTC, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import UserDep, require_role
from app.deps import get_db
from app.identity import account_for
from app.models import Employee, Invite, UserAccount, utcnow
from app.schemas import InviteClaim, InviteCreate, InviteOut, MeLink

DbDep = Annotated[Session, Depends(get_db)]

# Admin-only management of invites.
invites = APIRouter(prefix="/invites", tags=["identity"], dependencies=[require_role("admin")])
# Claiming needs only an authenticated Cognito login (staff group, not yet linked).
claim = APIRouter(prefix="/invites", tags=["identity"])

# Unambiguous alphabet (no 0/O/1/I) — the code is read aloud / typed at the salon.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _new_code(n: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


@invites.post("", status_code=status.HTTP_201_CREATED)
def create_invite(payload: InviteCreate, db: DbDep) -> InviteOut:
    emp = db.get(Employee, payload.employee_id)
    if emp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="employee not found")
    # Unique column protects us; retry on the astronomically unlikely collision.
    for _ in range(5):
        code = _new_code()
        if db.scalar(select(Invite).where(Invite.code == code)) is None:
            break
    else:  # pragma: no cover - 5 collisions on a 31^8 space is not a real branch
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="could not allocate code")
    invite = Invite(
        code=code,
        role="staff",
        employee_id=emp.id,
        expires_at=utcnow() + timedelta(days=payload.expires_in_days),
    )
    db.add(invite)
    db.flush()
    return InviteOut.model_validate(invite)


@invites.get("")
def list_invites(db: DbDep) -> list[InviteOut]:
    rows = db.scalars(select(Invite).order_by(Invite.created_at.desc())).all()
    return [InviteOut.model_validate(i) for i in rows]


@claim.post("/claim")
def claim_invite(payload: InviteClaim, user: UserDep, db: DbDep) -> MeLink:
    """Bind the caller's Cognito sub to the invite's employee. Idempotency and
    race safety: a sub already linked is rejected; the invite is claimed with a
    conditional UPDATE so only the first claim of a code wins."""
    if account_for(db, user.sub) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="account already linked")

    invite = db.scalar(select(Invite).where(Invite.code == payload.code.strip()))
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="invalid code")
    # SQLite returns naive datetimes for timezone=True columns (Postgres returns
    # aware); treat a naive expiry as the UTC we stored so the compare is portable.
    exp = invite.expires_at
    if exp is not None:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp < utcnow():
            raise HTTPException(status.HTTP_410_GONE, detail="code expired")

    # Atomic claim: succeeds only if still unclaimed (row-locked UPDATE on PG).
    claimed = db.execute(
        update(Invite)
        .where(Invite.id == invite.id, Invite.claimed_at.is_(None))
        .values(claimed_by_sub=user.sub, claimed_at=utcnow())
    )
    if claimed.rowcount == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="code already used")

    account = UserAccount(
        cognito_sub=user.sub,
        role=invite.role,
        employee_id=invite.employee_id,
        client_id=invite.client_id,
    )
    db.add(account)
    db.flush()

    emp = db.get(Employee, account.employee_id) if account.employee_id else None
    return MeLink(
        linked=True,
        role=account.role,
        employee_id=account.employee_id,
        display_name=emp.display_name if emp else None,
        fte_factor=emp.fte_factor if emp else None,
        pay_type=emp.pay_type if emp else None,
        is_active=emp.is_active if emp else None,
    )
