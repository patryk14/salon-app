"""F6 identity resolution: a Cognito `sub` → a domain row via UserAccount.

require_role() (auth.py) gates on the Cognito GROUP; these deps resolve the ROW
SCOPE — which employee a staff login *is* — so /me endpoints never trust a
client-supplied id. The account is created by claiming an invite (app.routers.
invites); until then a staff login is authenticated but unlinked.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import UserDep
from app.deps import get_db
from app.models import Employee, UserAccount

DbDep = Annotated[Session, Depends(get_db)]


def account_for(db: Session, sub: str) -> UserAccount | None:
    """The active UserAccount bound to this Cognito sub, if any."""
    return db.scalar(
        select(UserAccount).where(
            UserAccount.cognito_sub == sub, UserAccount.status == "active"
        )
    )


def current_employee(user: UserDep, db: DbDep) -> Employee:
    """The Employee this staff login is linked to. 403 until the account has
    claimed an invite — no silent fallback to an arbitrary employee, because a
    wrong link would leak another person's revenue."""
    account = account_for(db, user.sub)
    if account is None or account.employee_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="account not linked to an employee — claim an invite code first",
        )
    emp = db.get(Employee, account.employee_id)
    if emp is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="linked employee not found")
    return emp


EmployeeDep = Annotated[Employee, Depends(current_employee)]
