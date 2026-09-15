"""Client portal API (F7) — everything scoped to the caller's OWN client row.

require_role("client") gates the Cognito group; ClientDep (app.identity)
resolves the row scope from the token's sub, so a client login can only ever see
her own visits, packages and vouchers. Client.notes is never exposed here — the
note is staff/admin-only (owner rule). Admin passes the group gate but has no
client link, so /klient/me reports linked=false for the owner.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.auth import UserDep, require_role
from app.derivation import month_bounds
from app.identity import ClientDep, DbDep, account_for
from app.models import Client, Package, PackageRedemption, Visit, Voucher
from app.schemas import ClientMeOut, ClientPackageOut, ClientVoucherOut, VisitBrowseOut

MonthQuery = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]

client_portal = APIRouter(
    prefix="/klient", tags=["client-portal"], dependencies=[require_role("client")]
)


@client_portal.get("/me")
def whoami(user: UserDep, db: DbDep) -> ClientMeOut:
    """The caller's link state + light profile. Must NOT require a link — it's
    what drives the claim box on first login."""
    account = account_for(db, user.sub)
    if account is None or account.client_id is None:
        return ClientMeOut(linked=False)
    c = db.get(Client, account.client_id)
    if c is None:
        return ClientMeOut(linked=False)
    stats = db.execute(
        select(func.count(Visit.id), func.min(Visit.starts_at), func.max(Visit.starts_at)).where(
            Visit.client_id == account.client_id
        )
    ).one()
    return ClientMeOut(
        linked=True,
        client_id=c.id,
        first_name=c.first_name,
        last_name=c.last_name,
        phone=c.phone,
        email=c.email,
        total_visits=int(stats[0] or 0),
        first_visit=stats[1],
        last_visit=stats[2],
    )


@client_portal.get("/me/visits")
def my_visits(client: ClientDep, db: DbDep, month: MonthQuery) -> list[VisitBrowseOut]:
    """My visit history for the month (newest first)."""
    start, end = month_bounds(month)
    rows = db.scalars(
        select(Visit)
        .where(Visit.client_id == client.id, Visit.starts_at >= start, Visit.starts_at < end)
        .order_by(Visit.starts_at.desc())
    ).all()
    name = f"{client.first_name} {client.last_name}"
    return [
        VisitBrowseOut(
            id=v.id,
            starts_at=v.starts_at,
            client_name=name,
            service_name=v.service_name,
            staff_name=v.staff_name,
            price_pln=v.price_pln,
            status=v.status,
        )
        for v in rows
    ]


@client_portal.get("/me/packages")
def my_packages(client: ClientDep, db: DbDep) -> list[ClientPackageOut]:
    """My packages with the live remaining count (Booksy minus manual marks)."""
    manual = dict(
        db.execute(
            select(PackageRedemption.package_id, func.count())
            .where(
                PackageRedemption.source == "manual",
                PackageRedemption.package_id.is_not(None),
            )
            .group_by(PackageRedemption.package_id)
        ).all()
    )
    today = date.today()
    out: list[ClientPackageOut] = []
    for p in db.scalars(select(Package).where(Package.client_id == client.id)).all():
        remaining = max(0, p.remaining - int(manual.get(p.id, 0)))
        if remaining <= 0:
            status = "used_up"
        elif p.valid_until and p.valid_until < today:
            status = "expired"
        else:
            status = "active"
        out.append(
            ClientPackageOut(
                name=p.name,
                total_treatments=p.total_treatments,
                remaining=remaining,
                valid_until=p.valid_until,
                status=status,
            )
        )
    return out


@client_portal.get("/me/vouchers")
def my_vouchers(client: ClientDep, db: DbDep) -> list[ClientVoucherOut]:
    """My vouchers. Matched by name (vouchers aren't yet client-linked), so this
    is best-effort — the owner keeps the docx names close to the profile name."""
    full = f"{client.first_name} {client.last_name}".strip().lower()
    today = date.today()
    out: list[ClientVoucherOut] = []
    for v in db.scalars(select(Voucher)).all():
        if full not in v.client_name.strip().lower():
            continue
        if v.remaining_value <= 0:
            status = "used"
        elif v.valid_until and v.valid_until < today:
            status = "expired"
        else:
            status = "active"
        out.append(
            ClientVoucherOut(
                description=v.description,
                total_value=v.total_value,
                remaining_value=v.remaining_value,
                valid_until=v.valid_until,
                status=status,
            )
        )
    return out
