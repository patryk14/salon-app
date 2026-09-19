"""Client portal API (F7) — everything scoped to the caller's OWN client row.

require_role("client") gates the Cognito group; ClientDep (app.identity)
resolves the row scope from the token's sub, so a client login can only ever see
her own visits, packages and vouchers. Client.notes is never exposed here — the
note is staff/admin-only (owner rule). Admin passes the group gate but has no
client link, so /klient/me reports linked=false for the owner.
"""

import json
import urllib.request
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app import storage
from app.auth import UserDep, require_role
from app.config import get_settings
from app.derivation import month_bounds
from app.identity import ClientDep, DbDep, account_for
from app.models import (
    Client,
    Package,
    PackageRedemption,
    Photo,
    Service,
    UserAccount,
    Visit,
    Voucher,
)
from app.schemas import (
    ClientMeOut,
    ClientPackageOut,
    ClientVoucherOut,
    PhotoOut,
    RebookingSuggestion,
    VisitBrowseOut,
)

MonthQuery = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]

client_portal = APIRouter(
    prefix="/klient", tags=["client-portal"], dependencies=[require_role("client")]
)


def _client_me(db: DbDep, client_id: int) -> ClientMeOut:
    c = db.get(Client, client_id)
    if c is None:
        return ClientMeOut(linked=False)
    stats = db.execute(
        select(func.count(Visit.id), func.min(Visit.starts_at), func.max(Visit.starts_at)).where(
            Visit.client_id == client_id
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


@client_portal.get("/me")
def whoami(user: UserDep, db: DbDep) -> ClientMeOut:
    """The caller's link state + light profile. Must NOT require a link — it's
    what drives the claim box / signup flow on first login."""
    account = account_for(db, user.sub)
    if account is None or account.client_id is None:
        return ClientMeOut(linked=False)
    return _client_me(db, account.client_id)


def _verified_email(token: str) -> str | None:
    """The caller's VERIFIED email straight from Cognito's userInfo — never the
    client-supplied value, so it can't be spoofed to claim another profile."""
    domain = get_settings().cognito_domain
    if not domain or not token:
        return None
    req = urllib.request.Request(
        f"{domain}/oauth2/userInfo", headers={"authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (fixed https host)
            info = json.loads(resp.read())
    except Exception:
        return None
    if str(info.get("email_verified")).lower() != "true":
        return None
    email = (info.get("email") or "").strip().lower()
    return email or None


@client_portal.post("/me/link")
def auto_link(request: Request, user: UserDep, db: DbDep) -> ClientMeOut:
    """Auto-link a self-signed-up client to her Client row by VERIFIED email
    (F7 v2). Idempotent; unambiguous match only (0 or >1 → stays unlinked, the
    client falls back to an invite code)."""
    account = account_for(db, user.sub)
    if account is not None and account.client_id is not None:
        return _client_me(db, account.client_id)

    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    email = _verified_email(token)
    if not email:
        return ClientMeOut(linked=False)

    taken = select(UserAccount.client_id).where(UserAccount.client_id.is_not(None))
    matches = db.scalars(
        select(Client).where(func.lower(Client.email) == email, Client.id.not_in(taken))
    ).all()
    if len(matches) != 1:  # no match, or ambiguous → fall back to a code
        return ClientMeOut(linked=False)

    db.add(UserAccount(cognito_sub=user.sub, role="client", client_id=matches[0].id))
    db.flush()
    return _client_me(db, matches[0].id)


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


@client_portal.get("/me/rebooking")
def my_rebooking(client: ClientDep, db: DbDep) -> list[RebookingSuggestion]:
    """When to come back: for each service she's had that has a rebook interval,
    her last visit + the suggested next date (soonest first)."""
    catalog = {
        s.name: (s.rebook_interval_days, s.recommendation)
        for s in db.scalars(
            select(Service).where(
                Service.active.is_(True), Service.rebook_interval_days.is_not(None)
            )
        ).all()
    }
    if not catalog:
        return []
    rows = db.execute(
        select(Visit.service_name, func.max(Visit.starts_at))
        .where(
            Visit.client_id == client.id,
            Visit.status == "completed",
            Visit.service_name.in_(catalog),
        )
        .group_by(Visit.service_name)
    ).all()
    today = date.today()
    out: list[RebookingSuggestion] = []
    for service, last_dt in rows:
        if last_dt is None:
            continue
        interval_days, recommendation = catalog[service]
        last = last_dt.date() if hasattr(last_dt, "date") else last_dt
        nxt = last + timedelta(days=interval_days)
        out.append(
            RebookingSuggestion(
                service=service,
                last_visit=last,
                interval_days=interval_days,
                suggested_next=nxt,
                due=nxt <= today,
                recommendation=recommendation,
            )
        )
    out.sort(key=lambda x: x.suggested_next)
    return out


@client_portal.get("/me/photos")
def my_photos(client: ClientDep, db: DbDep) -> list[PhotoOut]:
    """My progress photos, newest first, each with a short-lived view URL. The
    uploader's identity (staff audit) is not exposed to the client."""
    photos = db.scalars(
        select(Photo)
        .where(Photo.client_id == client.id)
        .order_by(Photo.taken_on.desc(), Photo.created_at.desc())
    ).all()
    out: list[PhotoOut] = []
    for p in photos:
        item = PhotoOut.model_validate(p)
        item.uploaded_by = None
        item.url = storage.presign_get(p.s3_key)
        out.append(item)
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
