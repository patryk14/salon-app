"""Client profiles + their visits.

Gated to staff+admin (F0): the front desk needs client profiles day-to-day.
Row-scoped CLIENT access (a client seeing only herself) arrives with the
client portal slice — these endpoints stay staff-facing.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app import storage
from app.auth import UserDep, require_role
from app.deps import get_db
from app.derivation import month_bounds
from app.models import (
    BeautyPlan,
    CardMeasurement,
    CardSession,
    Client,
    ClientCard,
    ClientTombstone,
    Invite,
    Package,
    Photo,
    ProductSale,
    ShopOrder,
    UserAccount,
    Visit,
    utcnow,
)
from app.rodo import anonymise_client, ensure_real_client
from app.schemas import (
    ClientCreate,
    ClientOut,
    ClientUpdate,
    Page,
    VisitBrowseOut,
    VisitCreate,
    VisitOut,
    VisitUpdate,
)
from app.shop import actor_name, drop_client_orders

router = APIRouter(prefix="/clients", tags=["clients"], dependencies=[require_role("staff")])
visits_router = APIRouter(prefix="/visits", tags=["visits"], dependencies=[require_role("staff")])

DbDep = Annotated[Session, Depends(get_db)]


def _get_client_or_404(db: Session, client_id: int, mutable: bool = False) -> Client:
    """`mutable=True` for anything that edits / deletes / merges: the shared RODO
    placeholder holds other people's anonymised visits and must stay untouched."""
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="client not found")
    if mutable:
        ensure_real_client(client)
    return client


@router.get("")
def list_clients(
    db: DbDep,
    q: str | None = Query(default=None, max_length=100, description="search in name/phone"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ClientOut]:
    query = select(Client).where(Client.is_anonymous.is_(False))
    if q:
        pattern = f"%{' '.join(q.split())}%"
        # Full-name forms too: the front desk types "Karolina Sobas" (or "Sobas
        # Karolina"), which matches neither column alone.
        query = query.where(
            or_(
                Client.first_name.ilike(pattern),
                Client.last_name.ilike(pattern),
                Client.phone.ilike(pattern),
                (Client.first_name + " " + Client.last_name).ilike(pattern),
                (Client.last_name + " " + Client.first_name).ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(Client.last_name, Client.first_name).limit(limit).offset(offset)
    ).all()
    return Page[ClientOut](
        items=[ClientOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate, db: DbDep) -> ClientOut:
    client = Client(**payload.model_dump())
    db.add(client)
    db.flush()  # assigns the id within the request's transaction
    return ClientOut.model_validate(client)


@router.get("/{client_id}")
def get_client(client_id: int, db: DbDep) -> ClientOut:
    return ClientOut.model_validate(_get_client_or_404(db, client_id))


@router.patch("/{client_id}")
def update_client(client_id: int, payload: ClientUpdate, db: DbDep) -> ClientOut:
    client = _get_client_or_404(db, client_id, mutable=True)
    fields = payload.model_dump(exclude_unset=True)
    # Photo consent carries an audit timestamp: granting stamps now, revoking
    # clears it, so `photo_consent_at is not None` always means "consent stands".
    if "photo_consent" in fields:
        client.photo_consent_at = utcnow() if fields["photo_consent"] else None
    for field, value in fields.items():
        setattr(client, field, value)
    db.flush()
    return ClientOut.model_validate(client)


def _is_placeholder(value: str | None) -> bool:
    """Imports write "?" when Booksy/xlsx carried no surname."""
    return (value or "").strip() in ("", "?")


def _purge_client_storage(db: Session, client: Client) -> None:
    """Delete every S3 object behind this client's photos, so no bytes are
    orphaned in the bucket when her rows go away."""
    keys = list(db.scalars(select(Photo.s3_key).where(Photo.client_id == client.id)).all())
    storage.delete_objects(keys)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(client_id: int, user: UserDep, db: DbDep) -> None:
    """Ordinary delete (a duplicate/mistaken row): cascades to visits and photo
    rows and clears the S3 objects too — but leaves NO tombstone, so a Booksy
    backfill may legitimately recreate the client. RODO erasure is /erase."""
    client = _get_client_or_404(db, client_id, mutable=True)
    _purge_client_storage(db, client)
    drop_client_orders(db, client.id, sub=user.sub, name=actor_name(db, user))
    db.delete(client)


@router.post("/{client_id}/erase", dependencies=[require_role("admin")])
def erase_client(client_id: int, user: UserDep, db: DbDep) -> dict:
    """RODO right-to-be-forgotten (admin only): delete the client's S3 photos and
    all her rows, and — if she came from Booksy — leave a tombstone so the next
    `pull_customers` backfill does not silently recreate her.

    Two things do NOT hang off the client row and need explicit care: the stock her
    open orders reserved (released here, or it vanishes from the shelf), and her
    name inside the kept Booksy till rows (register_txns — scrubbed here). Booksy
    itself stays the salon's separate system of record: she must be deleted there
    too. Her visits are NOT deleted but anonymised (see app/rodo.py): the performer
    keeps her commission, and a suppression entry stops a re-import of those dates
    from recreating her."""
    client = _get_client_or_404(db, client_id, mutable=True)
    _purge_client_storage(db, client)
    drop_client_orders(db, client.id, sub=user.sub, name=actor_name(db, user))
    # her portal login dies with the row, but the Cognito user (her verified e-mail)
    # lives in the user pool — report it so it can be removed there as well
    logins = list(
        db.scalars(select(UserAccount.cognito_sub).where(UserAccount.client_id == client.id))
    )
    done = anonymise_client(db, client, date.today())
    tombstoned = client.booksy_customer_id is not None
    if tombstoned and db.get(ClientTombstone, client.booksy_customer_id) is None:
        db.add(ClientTombstone(booksy_customer_id=client.booksy_customer_id))
    # the visits were re-pointed with a bulk UPDATE — drop the ORM's stale view of
    # them, or deleting the client would cascade to rows that are no longer hers
    db.expire(client)
    db.delete(client)
    return {
        "erased": True,
        "tombstoned": tombstoned,
        "visits_anonymised": done.visits,
        # False = another client carries the same name, so unlinked records (vouchers,
        # never-imported history) could not be told apart and were left alone
        "name_suppressed": done.name_suppressed,
        "cognito_accounts": logins,
    }


@router.post("/{client_id}/merge-into/{target_id}", dependencies=[require_role("admin")])
def merge_client(client_id: int, target_id: int, db: DbDep) -> ClientOut:
    """Fold a duplicate profile into the real one (admin only). Everything the
    duplicate owns — visits, photos, packages, invites, portal login — moves to
    the target; the target's own contact data wins and only its GAPS are filled
    from the duplicate (incl. the Booksy id, so the next backfill updates the
    survivor instead of recreating the duplicate). Then the duplicate row goes.
    No S3 purge: the photo objects live on under the target."""
    if client_id == target_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="cannot merge a client into itself")
    source = _get_client_or_404(db, client_id, mutable=True)
    target = _get_client_or_404(db, target_id, mutable=True)

    def _login(cid: int) -> UserAccount | None:
        return db.scalar(select(UserAccount).where(UserAccount.client_id == cid))

    if _login(source.id) is not None and _login(target.id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="both profiles have a portal login — unlink one before merging",
        )

    # Treatment cards are unique per (client, type): where both profiles hold the
    # same type, the duplicate's sessions/measurements fold into the survivor's
    # card; the rest of her cards simply move over.
    target_cards = {
        c.card_type_id: c.id
        for c in db.scalars(select(ClientCard).where(ClientCard.client_id == target.id))
    }
    for card in db.scalars(select(ClientCard).where(ClientCard.client_id == source.id)).all():
        keep = target_cards.get(card.card_type_id)
        if keep is None:
            card.client_id = target.id
            continue
        for child in (CardSession, CardMeasurement):
            db.execute(update(child).where(child.card_id == card.id).values(card_id=keep))
        db.flush()
        db.expire(card)
        db.delete(card)
    # At most one ACTIVE beauty plan per client: the survivor's stays active.
    if db.scalar(
        select(BeautyPlan.id).where(
            BeautyPlan.client_id == target.id, BeautyPlan.status == "active"
        )
    ):
        db.execute(
            update(BeautyPlan)
            .where(BeautyPlan.client_id == source.id, BeautyPlan.status == "active")
            .values(status="archived")
        )

    for model in (Visit, Photo, Package, Invite, UserAccount, BeautyPlan, ShopOrder, ProductSale):
        db.execute(update(model).where(model.client_id == source.id).values(client_id=target.id))

    # Fill the survivor's gaps. The Booksy id is unique, so it must leave the
    # duplicate (flush) before it can land on the target.
    booksy_id = source.booksy_customer_id
    source.booksy_customer_id = None
    db.flush()
    if target.booksy_customer_id is None:
        target.booksy_customer_id = booksy_id
    elif booksy_id is not None and db.get(ClientTombstone, booksy_id) is None:
        # Both came from Booksy: the survivor keeps its own id, and the duplicate's
        # id is tombstoned — otherwise the next backfill would recreate it.
        db.add(ClientTombstone(booksy_customer_id=booksy_id, reason="merged"))
    # The better NAME survives, whichever side it is on: a "Karolina Sobas" / "?"
    # import artifact must not outlive a proper "Karolina" / "Sobas".
    if _is_placeholder(target.last_name) and not _is_placeholder(source.last_name):
        target.first_name, target.last_name = source.first_name, source.last_name
    for field in ("phone", "email", "notes"):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
    target.marketing_consent = target.marketing_consent or source.marketing_consent
    target.privacy_consent = target.privacy_consent or source.privacy_consent
    if source.photo_consent and not target.photo_consent:
        target.photo_consent = True
        target.photo_consent_at = source.photo_consent_at or utcnow()

    # The rows were re-pointed with bulk UPDATEs, so the ORM's cached collections
    # on `source` are stale — expire them, or the delete cascade would try to
    # remove children that now belong to the target.
    db.flush()
    db.expire(source)
    db.delete(source)
    db.flush()
    db.refresh(target)
    return ClientOut.model_validate(target)


@router.get("/{client_id}/visits")
def list_client_visits(
    client_id: int,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[VisitOut]:
    _get_client_or_404(db, client_id)
    base = select(Visit).where(Visit.client_id == client_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Visit.starts_at.desc()).limit(limit).offset(offset)).all()
    return Page[VisitOut](
        items=[VisitOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post("/{client_id}/visits", status_code=status.HTTP_201_CREATED)
def create_visit(client_id: int, payload: VisitCreate, db: DbDep) -> VisitOut:
    _get_client_or_404(db, client_id, mutable=True)
    visit = Visit(client_id=client_id, **payload.model_dump())
    db.add(visit)
    db.flush()
    return VisitOut.model_validate(visit)


@visits_router.get("")
def list_visits(
    db: DbDep,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
    q: str | None = Query(default=None, max_length=100, description="search client/service/staff"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[VisitBrowseOut]:
    """Browse the imported/pulled visits, newest first, with the client name."""
    # `+` on string columns → the `||` concat operator on both SQLite and Postgres
    # (func.concat would emit CONCAT(), which SQLite lacks).
    name = Client.first_name + " " + Client.last_name
    base = select(Visit, name.label("client_name")).join(Client, Visit.client_id == Client.id)
    if month:
        # date bounds, NOT f-string dates: comparing a TIMESTAMP column to a
        # VARCHAR works on SQLite but 500s on Postgres (operator type mismatch).
        start, end = month_bounds(month)
        base = base.where(Visit.starts_at >= start, Visit.starts_at < end)
    if q:
        pattern = f"%{q}%"
        base = base.where(
            or_(
                name.ilike(pattern),
                Visit.service_name.ilike(pattern),
                Visit.staff_name.ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(Visit.starts_at.desc()).limit(limit).offset(offset)).all()
    items = [
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
    return Page[VisitBrowseOut](items=items, total=total, limit=limit, offset=offset)


def _editable_visit(db: Session, visit_id: int) -> Visit:
    """An anonymised visit is a frozen business record: a note typed onto it ("to
    była Anna K.") would re-identify it, and deleting it would take the performer's
    commission — the very thing anonymising instead of deleting protects."""
    visit = db.get(Visit, visit_id)
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="visit not found")
    ensure_real_client(visit.client)
    return visit


@visits_router.patch("/{visit_id}")
def update_visit(visit_id: int, payload: VisitUpdate, db: DbDep) -> VisitOut:
    visit = _editable_visit(db, visit_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(visit, field, value)
    db.flush()
    return VisitOut.model_validate(visit)


@visits_router.delete("/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_visit(visit_id: int, db: DbDep) -> None:
    db.delete(_editable_visit(db, visit_id))
