"""Shop stock rules (F11) — shared by the staff router and the client portal.

Every change to products.stock_qty goes through `move_stock`, which writes the
movement row AND changes the counter in one statement guarded by
`stock_qty + delta >= 0`. Two people selling the last item at the same moment
therefore can't drive the shelf below zero: the second UPDATE matches no row.
"""

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.identity import account_for
from app.models import (
    Employee,
    Product,
    ProductSale,
    SettlementPeriod,
    ShopOrder,
    StockMovement,
)

LOW_STOCK = 2  # "ostatnie sztuki" in the client catalog
OPEN_ORDER = ("placed", "ready")
# Movements caused by a client (placing / cancelling her order) carry NO personal
# data: stock_movements does not die with the client row, so her name or Cognito
# id written here would survive a RODO erasure.
CLIENT_ACTOR = "klientka (portal)"


def actor_name(db: Session, user: CurrentUser) -> str:
    account = account_for(db, user.sub)
    if account is not None and account.employee_id is not None:
        emp = db.get(Employee, account.employee_id)
        if emp is not None:
            return emp.display_name
    return user.username


def own_employee_id(db: Session, user: CurrentUser) -> int | None:
    account = account_for(db, user.sub)
    return account.employee_id if account is not None else None


def move_stock(
    db: Session,
    product: Product,
    delta: int,
    reason: str,
    *,
    sub: str | None,
    name: str | None,
    ref: str | None = None,
    note: str | None = None,
    reveal_stock: bool = True,
) -> None:
    """`reveal_stock=False` for client-facing paths: she must never learn the
    exact figure on the shelf, not even from an error message."""
    if delta == 0:
        return
    changed = db.execute(
        update(Product)
        .where(Product.id == product.id, Product.stock_qty + delta >= 0)
        .values(stock_qty=Product.stock_qty + delta)
    ).rowcount
    if not changed:
        db.refresh(product)  # the figure we quote must be the current one
        detail = f"za mało sztuk na stanie: {product.name}"
        if reveal_stock:
            detail += f" (jest {product.stock_qty})"
        raise HTTPException(status.HTTP_409_CONFLICT, detail=detail)
    db.add(
        StockMovement(
            product_id=product.id,
            delta=delta,
            reason=reason,
            ref=ref,
            note=note,
            created_by_sub=sub,
            created_by_name=name,
        )
    )
    db.flush()
    db.refresh(product)


def claim_order(db: Session, order_id: int, allowed: tuple[str, ...], new_status: str) -> ShopOrder:
    """Move an order to `new_status` ATOMICALLY — one conditional UPDATE, checked
    by rowcount, BEFORE any side effect. A plain read-then-write lets two
    overlapping requests (a double click while Aurora wakes up, a client cancel
    racing a staff pickup) both pass the status check and both sell / release the
    same items. The loser of the race matches no row and gets a 409; if a later
    side effect fails, the transaction rolls the status back with everything else."""
    changed = db.execute(
        update(ShopOrder)
        .where(ShopOrder.id == order_id, ShopOrder.status.in_(allowed))
        .values(status=new_status)
    ).rowcount
    order = db.get(ShopOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="order not found")
    if not changed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"order is {order.status}")
    db.refresh(order)
    return order


def release_order_stock(
    db: Session, order: ShopOrder, *, sub: str | None, name: str | None
) -> None:
    """Put an order's reserved items back on the shelf."""
    for item in order.items:
        product = db.get(Product, item.product_id) if item.product_id else None
        if product is not None:
            move_stock(
                db, product, item.qty, "order_cancel", sub=sub, name=name, ref=f"order:{order.id}"
            )


def drop_client_orders(db: Session, client_id: int, *, sub: str | None, name: str | None) -> int:
    """Before a client row is deleted: return what her OPEN orders had reserved (or
    those items vanish from the shelf for good), delete ALL her orders, and detach
    her from past sales (the sale stays — it is someone's commission — but no longer
    points at her). Done explicitly rather than left to ON DELETE rules, so it
    behaves the same on every engine. Returns how many open orders were released."""
    orders = db.scalars(select(ShopOrder).where(ShopOrder.client_id == client_id)).all()
    released = 0
    for order in orders:
        if order.status in OPEN_ORDER:
            release_order_stock(db, order, sub=sub, name=name)
            released += 1
        db.delete(order)
    db.execute(update(ProductSale).where(ProductSale.client_id == client_id).values(client_id=None))
    db.flush()
    return released


def assert_period_open(db: Session, day: date) -> None:
    """Sales feed the month's settlement. Once that month is CLOSED it is a frozen,
    paid snapshot (and cannot be reopened): a sale added to it would never be paid,
    and one removed from it could be re-entered elsewhere and paid twice."""
    period = db.scalar(
        select(SettlementPeriod).where(SettlementPeriod.year_month == day.strftime("%Y-%m"))
    )
    if period is not None and period.status == "closed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"rozliczenie za {day:%Y-%m} jest zamknięte — sprzedaży nie można już zmieniać",
        )
