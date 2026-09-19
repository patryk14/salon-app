"""Shop (F11) — staff/admin facing: the product list, the shelf, sales, and the
pickup orders clients place from their portal.

Staff run the shop day to day (add / retire products, take deliveries, sell). A
sale is credited to the seller — for staff that is ALWAYS the employee linked to
their login (never a value from the request body); an admin may name the seller.
Product sales feed the SALES commission base (see derivation.monthly_shop_sales).
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, UserDep, require_role
from app.deps import get_db
from app.derivation import month_bounds
from app.models import (
    Client,
    Employee,
    Product,
    ProductSale,
    ShopOrder,
    ShopOrderItem,
    StockMovement,
)
from app.schemas import (
    OrderPickupIn,
    ProductIn,
    ProductOut,
    ProductSaleIn,
    ProductSaleOut,
    ProductUpdate,
    ShopOrderOut,
    StockChangeIn,
    StockMovementOut,
)
from app.shop import (
    OPEN_ORDER,
    actor_name,
    assert_period_open,
    claim_order,
    move_stock,
    own_employee_id,
    release_order_stock,
)

router = APIRouter(prefix="/shop", tags=["shop"], dependencies=[require_role("staff")])

DbDep = Annotated[Session, Depends(get_db)]
MonthQuery = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def _product(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="product not found")
    return p


def _seller_id(db: Session, user: CurrentUser, requested: int | None) -> int | None:
    """Who earns the commission. Staff → their own employee, whatever the body
    says. Admin → the employee they picked, or nobody (the owner's own sale)."""
    if "admin" in user.groups:
        if requested is not None and db.get(Employee, requested) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="employee not found")
        return requested
    emp_id = own_employee_id(db, user)
    if emp_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="account not linked to an employee — claim an invite code first",
        )
    return emp_id


# -------------------------------------------------------------------- products
@router.get("/products")
def list_products(db: DbDep, include_inactive: bool = False) -> list[ProductOut]:
    q = select(Product).order_by(Product.active.desc(), Product.name)
    if not include_inactive:
        q = q.where(Product.active.is_(True))
    return [ProductOut.model_validate(p) for p in db.scalars(q)]


@router.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductIn, user: UserDep, db: DbDep) -> ProductOut:
    if _name_taken(db, payload.name):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="produkt o tej nazwie już istnieje")
    data = payload.model_dump()
    opening = data.pop("stock_qty")
    product = Product(**{**data, "name": payload.name.strip()}, created_by=user.sub)
    db.add(product)
    db.flush()
    move_stock(
        db,
        product,
        opening,
        "delivery",
        sub=user.sub,
        name=actor_name(db, user),
        note="stan początkowy",
    )
    return ProductOut.model_validate(product)


def _name_taken(db: Session, name: str, except_id: int | None = None) -> bool:
    q = select(Product.id).where(func.lower(Product.name) == name.strip().lower())
    if except_id is not None:
        q = q.where(Product.id != except_id)
    return db.scalar(q) is not None


@router.patch("/products/{product_id}")
def update_product(product_id: int, payload: ProductUpdate, db: DbDep) -> ProductOut:
    product = _product(db, product_id)
    fields = payload.model_dump(exclude_unset=True)
    # name / price / active are NOT NULL: an explicit null means "leave it", not a 500
    for required in ("name", "price_pln", "active"):
        if fields.get(required, 0) is None:
            del fields[required]
    if "name" in fields:
        fields["name"] = fields["name"].strip()
        if _name_taken(db, fields["name"], except_id=product.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="produkt o tej nazwie już istnieje"
            )
    for field, value in fields.items():
        setattr(product, field, value)
    db.flush()
    return ProductOut.model_validate(product)


@router.delete("/products/{product_id}")
def remove_product(product_id: int, db: DbDep) -> dict:
    """Take a product out of the shop. If it was ever sold or ordered it is only
    retired (history and commission stay intact); otherwise it is deleted."""
    product = _product(db, product_id)
    has_history = db.scalar(
        select(ProductSale.id).where(ProductSale.product_id == product_id).limit(1)
    ) or db.scalar(select(ShopOrderItem.id).where(ShopOrderItem.product_id == product_id).limit(1))
    if has_history:
        product.active = False
        return {"removed": "retired"}
    db.delete(product)
    return {"removed": "deleted"}


@router.post("/products/{product_id}/stock")
def change_stock(product_id: int, payload: StockChangeIn, user: UserDep, db: DbDep) -> ProductOut:
    """A delivery (+) or a stocktaking correction (±)."""
    product = _product(db, product_id)
    if payload.reason == "delivery" and payload.delta <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="dostawa musi być dodatnia")
    move_stock(
        db,
        product,
        payload.delta,
        payload.reason,
        sub=user.sub,
        name=actor_name(db, user),
        note=payload.note,
    )
    return ProductOut.model_validate(product)


@router.get("/products/{product_id}/movements")
def list_movements(product_id: int, user: UserDep, db: DbDep) -> list[StockMovementOut]:
    """The shelf's audit trail. Admin sees who did what; staff see names only on
    their OWN rows — a "sale by Julia" line would otherwise tell everyone what a
    colleague sold, which is her commission and nobody else's business."""
    _product(db, product_id)
    rows = db.scalars(
        select(StockMovement)
        .where(StockMovement.product_id == product_id)
        .order_by(StockMovement.id.desc())
        .limit(100)
    ).all()
    is_admin = "admin" in user.groups
    out = []
    for r in rows:
        item = StockMovementOut.model_validate(r)
        if not is_admin and r.created_by_sub != user.sub:
            item.created_by_name = None
        out.append(item)
    return out


# ----------------------------------------------------------------------- sales
def _sale_out(db: Session, sale: ProductSale) -> ProductSaleOut:
    out = ProductSaleOut.model_validate(sale)
    if sale.employee_id is not None:
        emp = db.get(Employee, sale.employee_id)
        out.employee_name = emp.display_name if emp else None
    return out


def record_sale(
    db: Session,
    user: CurrentUser,
    product: Product,
    qty: int,
    *,
    unit_price: Decimal,
    employee_id: int | None,
    payment_method: str,
    sold_on: date,
    client_id: int | None = None,
    order_id: int | None = None,
    take_from_stock: bool = True,
) -> ProductSale:
    sale = ProductSale(
        product_id=product.id,
        product_name=product.name,
        qty=qty,
        unit_price=unit_price,
        total=unit_price * qty,
        sold_on=sold_on,
        payment_method=payment_method,
        employee_id=employee_id,
        client_id=client_id,
        order_id=order_id,
        created_by_sub=user.sub,
    )
    db.add(sale)
    db.flush()
    if take_from_stock:
        move_stock(
            db,
            product,
            -qty,
            "sale",
            sub=user.sub,
            name=actor_name(db, user),
            ref=f"sale:{sale.id}",
        )
    return sale


@router.post("/sales", status_code=status.HTTP_201_CREATED)
def sell(payload: ProductSaleIn, user: UserDep, db: DbDep) -> ProductSaleOut:
    product = _product(db, payload.product_id)
    if not product.active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="produkt wycofany ze sklepu")
    if payload.client_id is not None and db.get(Client, payload.client_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="client not found")
    # The sales commission is a cliff (0% below 1500, 10% of everything from it),
    # so WHICH month a sale lands in is money. Staff therefore sell "today", full
    # stop; only an admin may back-date a forgotten sale — never into the future.
    today = date.today()
    sold_on = (payload.sold_on or today) if "admin" in user.groups else today
    if sold_on > today:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="data sprzedaży z przyszłości")
    assert_period_open(db, sold_on)
    sale = record_sale(
        db,
        user,
        product,
        payload.qty,
        unit_price=product.price_pln,
        employee_id=_seller_id(db, user, payload.employee_id),
        payment_method=payload.payment_method,
        sold_on=sold_on,
        client_id=payload.client_id,
    )
    return _sale_out(db, sale)


@router.get("/sales")
def list_sales(db: DbDep, user: UserDep, month: MonthQuery) -> list[ProductSaleOut]:
    """The month's sales. Admin sees everyone's; staff see only their own — what
    a colleague sold is her commission, not shared information."""
    start, end = month_bounds(month)
    q = (
        select(ProductSale)
        .where(ProductSale.sold_on >= start, ProductSale.sold_on < end)
        .order_by(ProductSale.sold_on.desc(), ProductSale.id.desc())
    )
    if "admin" not in user.groups:
        q = q.where(ProductSale.employee_id == (own_employee_id(db, user) or -1))
    return [_sale_out(db, s) for s in db.scalars(q)]


@router.delete("/sales/{sale_id}", status_code=status.HTTP_204_NO_CONTENT)
def void_sale(sale_id: int, user: UserDep, db: DbDep) -> None:
    """Undo a mistaken sale: the items go back on the shelf."""
    sale = db.get(ProductSale, sale_id)
    if sale is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="sale not found")
    if "admin" not in user.groups and (
        sale.created_by_sub != user.sub or sale.sold_on != date.today()
    ):
        # staff fix their own slip of the same day; anything older goes through the
        # owner — otherwise a sale could be voided and re-entered in a better month
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="możesz anulować tylko własną dzisiejszą sprzedaż — starsze: administrator",
        )
    assert_period_open(db, sale.sold_on)
    # also for a sale that came from an order pickup: those items left the shelf when
    # the order was placed, and voiding the sale puts them physically back
    if sale.product_id is not None:
        product = _product(db, sale.product_id)
        move_stock(
            db,
            product,
            sale.qty,
            "correction",
            sub=user.sub,
            name=actor_name(db, user),
            ref=f"sale:{sale.id}",
            note="anulowana sprzedaż",
        )
    db.delete(sale)


# ---------------------------------------------------------------------- orders
def order_out(db: Session, order: ShopOrder) -> ShopOrderOut:
    out = ShopOrderOut.model_validate(order)
    client = db.get(Client, order.client_id)
    out.client_name = f"{client.first_name} {client.last_name}" if client else None
    out.total = sum((i.price_at_order * i.qty for i in order.items), Decimal("0"))
    return out


@router.get("/orders")
def list_orders(db: DbDep, open_only: bool = True) -> list[ShopOrderOut]:
    q = select(ShopOrder).order_by(ShopOrder.id.desc()).limit(200)
    if open_only:
        q = q.where(ShopOrder.status.in_(("placed", "ready")))
    return [order_out(db, o) for o in db.scalars(q)]


@router.post("/orders/{order_id}/ready")
def mark_ready(order_id: int, user: UserDep, db: DbDep) -> ShopOrderOut:
    order = claim_order(db, order_id, ("placed",), "ready")
    order.handled_by_name = actor_name(db, user)
    return order_out(db, order)


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, user: UserDep, db: DbDep) -> ShopOrderOut:
    order = claim_order(db, order_id, OPEN_ORDER, "cancelled")
    release_order_stock(db, order, sub=user.sub, name=actor_name(db, user))
    order.handled_by_name = actor_name(db, user)
    return order_out(db, order)


@router.post("/orders/{order_id}/pickup")
def pickup_order(order_id: int, payload: OrderPickupIn, user: UserDep, db: DbDep) -> ShopOrderOut:
    """The client collected and paid: each item becomes a sale credited to whoever
    hands it over. Stock was already reserved when the order was placed."""
    seller = _seller_id(db, user, payload.employee_id)
    today = date.today()
    assert_period_open(db, today)
    order = claim_order(db, order_id, OPEN_ORDER, "picked_up")  # atomic: never sells twice
    for item in order.items:
        product = db.get(Product, item.product_id) if item.product_id else None
        if product is None:
            continue
        record_sale(
            db,
            user,
            product,
            item.qty,
            unit_price=item.price_at_order,
            employee_id=seller,
            payment_method=payload.payment_method,
            sold_on=today,
            client_id=order.client_id,
            order_id=order.id,
            take_from_stock=False,
        )
    order.handled_by_name = actor_name(db, user)
    return order_out(db, order)
