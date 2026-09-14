"""Bank-statement import (MT940 → expenses) — admin-only, slice 2 of F12.

Upload an ING `.sta` file → its debits are parsed, deduped on the bank
reference, and staged for review with a suggested category. The owner assigns
the ambiguous ones (payment aggregators) and ignores the non-costs (staff
salaries — derived from settlements — and owner draws), then materializes the
month: staged rows become Expense lines grouped per (category, label), and the
template 'recurring' estimates are cleared in favor of the bank's real amounts.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.deps import get_db
from app.models import Expense, ExpenseCategory, PnlMonth, StatementTxn
from app.pnl import ensure_categories
from app.schemas import (
    StatementImportSummary,
    StatementMaterializeSummary,
    StatementTxnOut,
    StatementTxnUpdate,
)
from app.statement import parse_mt940

DbDep = Annotated[Session, Depends(get_db)]
MonthQuery = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def _ensure(db: DbDep) -> None:
    ensure_categories(db)


router = APIRouter(
    prefix="/statements",
    tags=["statements"],
    dependencies=[require_role("admin"), Depends(_ensure)],
)


def _out(t: StatementTxn) -> StatementTxnOut:
    return StatementTxnOut(
        id=t.id,
        value_date=t.value_date,
        amount=t.amount,
        counterparty=t.counterparty,
        title=t.title,
        category=t.category,
        name=t.name,
        bucket=t.bucket,
        status=t.status,
    )


@router.post("/import")
def import_statement(
    db: DbDep,
    file: Annotated[UploadFile, File(description="ING MT940 (.sta) statement")],
) -> StatementImportSummary:
    """Parse a statement's debits and stage the new ones (idempotent on the bank
    reference). Staff salaries and owner draws land pre-marked 'ignored'."""
    try:
        txns = parse_mt940(file.file.read())
    except Exception as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Nie udało się odczytać pliku MT940 (.sta)."
        ) from e
    if not txns:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Brak obciążeń w pliku.")

    existing = set(db.scalars(select(StatementTxn.bank_ref)).all())
    added = duplicates = needs_review = 0
    months: dict[str, int] = {}
    for t in txns:
        if t.bank_ref in existing:
            duplicates += 1
            continue
        ym = t.value_date.strftime("%Y-%m")
        months[ym] = months.get(ym, 0) + 1
        row_status = "ignored" if t.bucket in ("staff", "owner_draw") else "pending"
        db.add(
            StatementTxn(
                bank_ref=t.bank_ref,
                year_month=ym,
                value_date=t.value_date,
                amount=t.amount,
                counterparty=t.counterparty,
                title=t.title,
                category=t.suggested_category,
                name=t.suggested_name,
                bucket=t.bucket,
                status=row_status,
            )
        )
        existing.add(t.bank_ref)
        added += 1
        if row_status == "pending" and t.suggested_category is None:
            needs_review += 1
    db.flush()
    dominant = max(months, key=lambda m: months[m]) if months else ""
    return StatementImportSummary(
        year_month=dominant,
        parsed=len(txns),
        added=added,
        duplicates=duplicates,
        needs_review=needs_review,
    )


@router.get("")
def list_txns(db: DbDep, month: MonthQuery) -> list[StatementTxnOut]:
    rows = db.scalars(
        select(StatementTxn)
        .where(StatementTxn.year_month == month)
        .order_by(StatementTxn.value_date, StatementTxn.id)
    ).all()
    return [_out(r) for r in rows]


@router.put("/{txn_id}")
def update_txn(txn_id: int, payload: StatementTxnUpdate, db: DbDep) -> StatementTxnOut:
    t = db.get(StatementTxn, txn_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej pozycji.")
    if t.status == "imported":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Pozycja już rozliczona — zmień koszt w panelu P&L."
        )
    if payload.clear_category:
        t.category = None
    elif payload.category is not None:
        t.category = payload.category
    if payload.name is not None:
        t.name = payload.name.strip()
    if payload.status is not None:
        if payload.status not in ("pending", "ignored"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Zły status.")
        t.status = payload.status
    db.flush()
    return _out(t)


@router.post("/materialize")
def materialize(db: DbDep, month: MonthQuery) -> StatementMaterializeSummary:
    """Turn the month's assigned staging rows into grouped Expense lines and clear
    the template estimates — the bank's real amounts win."""
    row = db.scalar(select(PnlMonth).where(PnlMonth.year_month == month))
    if row is None:
        row = PnlMonth(year_month=month, status="draft")  # opened, no recurring prefill
        db.add(row)
        db.flush()
    if row.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Miesiąc zamknięty.")

    recurring_cleared = 0
    for e in db.scalars(
        select(Expense).where(Expense.year_month == month, Expense.source == "recurring")
    ).all():
        db.delete(e)
        recurring_cleared += 1

    cat_ids = {c.code: c.id for c in db.scalars(select(ExpenseCategory)).all()}
    groups: dict[tuple[str, str], list[StatementTxn]] = {}
    unassigned = 0
    for t in db.scalars(
        select(StatementTxn).where(
            StatementTxn.year_month == month, StatementTxn.status == "pending"
        )
    ).all():
        if not t.category or t.category not in cat_ids:
            unassigned += 1
            continue
        groups.setdefault((t.category, t.name), []).append(t)

    created = imported = 0
    for (code, name), txns in groups.items():
        exp = Expense(
            year_month=month,
            category_id=cat_ids[code],
            name=name,
            amount_pln=sum((t.amount for t in txns), Decimal("0")),
            source="statement",
        )
        db.add(exp)
        db.flush()
        created += 1
        for t in txns:
            t.status = "imported"
            t.expense_id = exp.id
            imported += 1
    db.flush()
    return StatementMaterializeSummary(
        year_month=month,
        expenses_created=created,
        txns_imported=imported,
        unassigned=unassigned,
        recurring_cleared=recurring_cleared,
    )
