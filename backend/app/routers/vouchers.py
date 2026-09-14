"""Vouchers (gift cards) — admin-only, value-based, tracked by hand.

Booksy has no voucher entity (a voucher-paid visit is a normal service there),
so vouchers live only here and never touch the commission base. Partial
redemptions draw down the balance with an audit trail (who + when). The list can
be seeded best-effort from the owner's VOUCHERY.docx; she curates from there.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import UserDep, require_role
from app.deps import get_db
from app.models import Voucher, VoucherRedemption
from app.schemas import (
    VoucherCreate,
    VoucherImportSummary,
    VoucherOut,
    VoucherRedeemIn,
    VoucherRedemptionOut,
    VoucherUpdate,
)
from app.vouchers_import import parse_vouchers_docx

DbDep = Annotated[Session, Depends(get_db)]

router = APIRouter(prefix="/vouchers", tags=["vouchers"], dependencies=[require_role("admin")])


def _status(v: Voucher) -> str:
    if v.remaining_value <= 0:
        return "used"
    if v.valid_until is not None and v.valid_until < date.today():
        return "expired"
    return "active"


def _out(v: Voucher) -> VoucherOut:
    return VoucherOut(
        id=v.id,
        client_name=v.client_name,
        description=v.description,
        total_value=v.total_value,
        remaining_value=v.remaining_value,
        purchased_on=v.purchased_on,
        valid_until=v.valid_until,
        status=_status(v),
        note=v.note,
        source=v.source,
        redemptions=[
            VoucherRedemptionOut(
                id=r.id,
                amount=r.amount,
                redeemed_on=r.redeemed_on,
                note=r.note,
                created_by=r.created_by,
                created_at=r.created_at,
            )
            for r in sorted(v.redemptions, key=lambda r: r.redeemed_on)
        ],
    )


@router.get("")
def list_vouchers(
    db: DbDep, status_filter: Annotated[str | None, Query(alias="status")] = None
) -> list[VoucherOut]:
    rows = db.scalars(
        select(Voucher).order_by(Voucher.valid_until.desc().nullslast(), Voucher.id.desc())
    ).all()
    out = [_out(v) for v in rows]
    if status_filter:
        out = [v for v in out if v.status == status_filter]
    return out


@router.post("")
def create_voucher(payload: VoucherCreate, user: UserDep, db: DbDep) -> VoucherOut:
    v = Voucher(
        client_name=payload.client_name.strip(),
        description=payload.description.strip(),
        total_value=payload.total_value,
        remaining_value=payload.remaining_value
        if payload.remaining_value is not None
        else payload.total_value,
        purchased_on=payload.purchased_on,
        valid_until=payload.valid_until,
        note=payload.note,
        source="manual",
        created_by=user.username,
    )
    db.add(v)
    db.flush()
    return _out(v)


@router.put("/{voucher_id}")
def update_voucher(voucher_id: int, payload: VoucherUpdate, db: DbDep) -> VoucherOut:
    v = db.get(Voucher, voucher_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego vouchera.")
    if payload.client_name is not None:
        v.client_name = payload.client_name.strip()
    if payload.description is not None:
        v.description = payload.description.strip()
    if payload.total_value is not None:
        v.total_value = payload.total_value
    if payload.remaining_value is not None:
        v.remaining_value = payload.remaining_value
    if payload.valid_until is not None:
        v.valid_until = payload.valid_until
    if payload.note is not None:
        v.note = payload.note
    db.flush()
    return _out(v)


@router.delete("/{voucher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voucher(voucher_id: int, db: DbDep) -> None:
    v = db.get(Voucher, voucher_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego vouchera.")
    db.delete(v)
    db.flush()


@router.post("/{voucher_id}/redeem")
def redeem_voucher(
    voucher_id: int, payload: VoucherRedeemIn, user: UserDep, db: DbDep
) -> VoucherOut:
    """Draw `amount` against the voucher (audit: who + when)."""
    v = db.get(Voucher, voucher_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego vouchera.")
    if payload.amount > v.remaining_value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Kwota {payload.amount} przekracza pozostałe {v.remaining_value} zł.",
        )
    db.add(
        VoucherRedemption(
            voucher_id=v.id,
            amount=payload.amount,
            redeemed_on=payload.redeemed_on or date.today(),
            note=payload.note,
            created_by=user.username,
        )
    )
    v.remaining_value = v.remaining_value - payload.amount
    db.flush()
    db.refresh(v)
    return _out(v)


@router.post("/import")
def import_vouchers(
    db: DbDep,
    file: Annotated[UploadFile, File(description="VOUCHERY.docx")],
) -> VoucherImportSummary:
    """Best-effort seed of ACTIVE vouchers from the docx. Skips rows without a
    parseable value; imports only ones still (plausibly) active — the owner
    curates the rest. Deduped on (client, purchase date, value)."""
    try:
        parsed = parse_vouchers_docx(file.file.read())
    except Exception as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Nie udało się odczytać pliku .docx."
        ) from e

    today = date.today()
    recent = today - timedelta(days=150)
    existing = {
        (v.client_name, v.purchased_on, v.total_value) for v in db.scalars(select(Voucher)).all()
    }
    imported = skipped_existing = skipped_inactive = 0
    for p in parsed:
        active = (p.valid_until is not None and p.valid_until >= today) or (
            p.valid_until is None and p.purchased_on is not None and p.purchased_on >= recent
        )
        if not active:
            skipped_inactive += 1
            continue
        key = (p.client_name, p.purchased_on, p.total_value)
        if key in existing:
            skipped_existing += 1
            continue
        db.add(
            Voucher(
                client_name=p.client_name,
                description=p.description,
                total_value=p.total_value,
                remaining_value=p.total_value,  # owner adjusts partially-used ones
                purchased_on=p.purchased_on,
                valid_until=p.valid_until,
                source="docx",
            )
        )
        existing.add(key)
        imported += 1
    db.flush()
    return VoucherImportSummary(
        parsed=len(parsed),
        imported=imported,
        skipped_existing=skipped_existing,
        skipped_inactive=skipped_inactive,
    )
