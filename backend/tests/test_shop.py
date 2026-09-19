"""Shop (F11): staff-run product list with a real shelf, sales that feed the SALES
commission (10% once a month's sales reach 1500 zł), and pickup orders placed by
clients from their portal. Stock only ever changes through a movement row."""

from decimal import Decimal

from fastapi.testclient import TestClient


def money(v) -> Decimal:
    return Decimal(str(v))


def _product(c: TestClient, name="Krem SPF 50", price="120.00", stock=5) -> dict:
    r = c.post("/shop/products", json={"name": name, "price_pln": price, "stock_qty": stock})
    assert r.status_code == 201, r.text
    return r.json()


def _employee(c: TestClient, name="Julia") -> int:
    return c.post("/employees", json={"display_name": name, "fte_factor": "1.0"}).json()["id"]


def _link_staff(c: TestClient, emp_id: int, sub: str) -> None:
    c.as_user("test-admin", {"admin"})
    code = c.post("/invites", json={"employee_id": emp_id}).json()["code"]
    c.as_user(sub, {"staff"})
    assert c.post("/invites/claim", json={"code": code}).status_code == 200


def _link_client(c: TestClient, cid: int, sub: str) -> None:
    c.as_user("test-admin", {"admin"})
    code = c.post("/invites", json={"client_id": cid}).json()["code"]
    c.as_user(sub, {"client"})
    assert c.post("/invites/claim", json={"code": code}).status_code == 200


def test_product_lifecycle_and_stock_audit(db_client: TestClient) -> None:
    c = db_client
    p = _product(c, stock=3)
    assert p["stock_qty"] == 3
    assert (
        c.post("/shop/products", json={"name": " krem spf 50 ", "price_pln": "1"}).status_code
        == 409
    )

    after = c.post(f"/shop/products/{p['id']}/stock", json={"delta": 10, "reason": "delivery"})
    assert after.json()["stock_qty"] == 13
    assert (
        c.post(
            f"/shop/products/{p['id']}/stock", json={"delta": -2, "reason": "delivery"}
        ).status_code
        == 400
    )  # a delivery can't be negative — that's a correction
    c.post(
        f"/shop/products/{p['id']}/stock",
        json={"delta": -1, "reason": "correction", "note": "stłuczony"},
    )
    # the shelf can never go below zero
    assert (
        c.post(
            f"/shop/products/{p['id']}/stock", json={"delta": -99, "reason": "correction"}
        ).status_code
        == 409
    )

    moves = c.get(f"/shop/products/{p['id']}/movements").json()
    assert [(m["delta"], m["reason"]) for m in moves] == [
        (-1, "correction"), (10, "delivery"), (3, "delivery")]  # fmt: skip
    assert moves[0]["created_by_name"] == "test-admin" and moves[0]["note"] == "stłuczony"
    assert sum(m["delta"] for m in moves) == c.get("/shop/products").json()[0]["stock_qty"] == 12

    # never sold → really deleted; sold → only retired, history stays
    assert c.delete(f"/shop/products/{p['id']}").json() == {"removed": "deleted"}
    q = _product(c, "Serum", "200.00", 2)
    c.post("/shop/sales", json={"product_id": q["id"], "qty": 1})
    assert c.delete(f"/shop/products/{q['id']}").json() == {"removed": "retired"}
    assert c.get("/shop/products").json() == []
    assert [x["active"] for x in c.get("/shop/products?include_inactive=true").json()] == [False]
    assert c.post("/shop/sales", json={"product_id": q["id"], "qty": 1}).status_code == 409


def test_sale_takes_stock_and_void_returns_it(db_client: TestClient) -> None:
    c = db_client
    p = _product(c, stock=2)
    sale = c.post(
        "/shop/sales", json={"product_id": p["id"], "qty": 2, "payment_method": "gotowka"}
    )
    assert sale.status_code == 201, sale.text
    assert money(sale.json()["total"]) == money("240.00")
    assert c.post("/shop/sales", json={"product_id": p["id"], "qty": 1}).status_code == 409  # empty
    # a later price change must not rewrite history
    c.patch(f"/shop/products/{p['id']}", json={"price_pln": "999"})
    month = sale.json()["sold_on"][:7]
    assert money(c.get(f"/shop/sales?month={month}").json()[0]["total"]) == money("240.00")

    assert c.delete(f"/shop/sales/{sale.json()['id']}").status_code == 204
    assert c.get("/shop/products").json()[0]["stock_qty"] == 2
    assert c.get(f"/shop/sales?month={month}").json() == []


def test_staff_sell_as_themselves_and_see_only_their_sales(portal_client: TestClient) -> None:
    c = portal_client
    p = _product(c, stock=10)
    julia, ola = _employee(c, "Julia"), _employee(c, "Ola")
    _link_staff(c, julia, "sub-julia")
    _link_staff(c, ola, "sub-ola")

    c.as_user("sub-julia", {"staff"})
    # the body tries to credit Ola — ignored: staff always sell as themselves
    s = c.post("/shop/sales", json={"product_id": p["id"], "qty": 1, "employee_id": ola}).json()
    assert s["employee_id"] == julia and s["employee_name"] == "Julia"
    month = s["sold_on"][:7]

    c.as_user("sub-ola", {"staff"})
    assert (
        c.get(f"/shop/sales?month={month}").json() == []
    )  # a colleague's sales aren't hers to see
    assert c.delete(f"/shop/sales/{s['id']}").status_code == 403

    c.as_user("unlinked-staff", {"staff"})
    assert c.post("/shop/sales", json={"product_id": p["id"], "qty": 1}).status_code == 403

    c.as_user("test-admin", {"admin"})
    assert len(c.get(f"/shop/sales?month={month}").json()) == 1
    # admin may credit an employee, or nobody (the owner's own sale)
    assert (
        c.post("/shop/sales", json={"product_id": p["id"], "employee_id": ola}).json()[
            "employee_id"
        ]
        == ola
    )
    assert c.post("/shop/sales", json={"product_id": p["id"]}).json()["employee_id"] is None
    assert (
        c.post("/shop/sales", json={"product_id": p["id"], "employee_id": 9999}).status_code == 400
    )


def test_shop_sales_feed_the_sales_commission(portal_client: TestClient) -> None:
    """Below 1500 zł of product sales: no sales commission. At 1500: 10% of all."""
    c = portal_client
    julia = _employee(c, "Julia")
    p = _product(c, "Zestaw", "500.00", 10)
    ym = "2026-09"
    for _ in range(2):
        c.post(
            "/shop/sales", json={"product_id": p["id"], "employee_id": julia, "sold_on": f"{ym}-10"}
        )
    c.post("/settlement/periods", json={"year_month": ym})
    line = c.post(f"/settlement/periods/{ym}/lines/{julia}/derive").json()
    assert money(line["shop_sales"]) == money("1000") and money(line["sales_commission"]) == 0

    c.post("/shop/sales", json={"product_id": p["id"], "employee_id": julia, "sold_on": f"{ym}-11"})
    c.post(
        "/shop/sales", json={"product_id": p["id"], "employee_id": julia, "sold_on": "2026-10-01"}
    )
    line = c.post(f"/settlement/periods/{ym}/lines/{julia}/derive").json()
    assert money(line["shop_sales"]) == money("1500")  # October's sale is not September's
    assert money(line["sales_base"]) == money("1500")
    assert money(line["sales_commission"]) == money("150")

    # hand-typed Booksy product sales still add on top; editing one cell keeps shop_sales
    put = c.put(
        f"/settlement/periods/{ym}/lines/{julia}",
        json={"booksy_sales": "100", "shop_sales": line["shop_sales"]},
    ).json()
    assert money(put["sales_base"]) == money("1600") and money(put["sales_commission"]) == money(
        "160"
    )

    # her own live preview shows the same base
    _link_staff(c, julia, "sub-julia")
    me = c.get(f"/me/commission?month={ym}").json()
    assert money(me["sales_base"]) == money("1500") and money(me["sales_commission"]) == money(
        "150"
    )


def test_client_orders_reserve_stock_and_pickup_becomes_a_sale(portal_client: TestClient) -> None:
    c = portal_client
    julia = _employee(c, "Julia")
    krem, serum = _product(c, "Krem", "100.00", 2), _product(c, "Serum", "50.00", 1)
    hidden = _product(c, "Wycofany", "10.00", 5)
    c.patch(f"/shop/products/{hidden['id']}", json={"active": False})
    cid = c.post("/clients", json={"first_name": "Ewa", "last_name": "Nowak"}).json()["id"]
    other = c.post("/clients", json={"first_name": "Inna", "last_name": "Osoba"}).json()["id"]
    _link_client(c, cid, "sub-ewa")

    cat = {x["name"]: x for x in c.get("/klient/shop/products").json()}
    assert set(cat) == {"Krem", "Serum"} and "stock_qty" not in cat["Krem"]
    assert cat["Serum"]["available"] and cat["Serum"]["low_stock"]

    too_many = c.post("/klient/me/orders", json={"items": [{"product_id": krem["id"], "qty": 3}]})
    assert too_many.status_code == 409
    assert (
        c.post(
            "/klient/me/orders", json={"items": [{"product_id": hidden["id"], "qty": 1}]}
        ).status_code
        == 400
    )
    order = c.post(
        "/klient/me/orders",
        json={
            "items": [{"product_id": krem["id"], "qty": 2}, {"product_id": serum["id"], "qty": 1}]
        },
    )
    assert order.status_code == 201, order.text
    oid = order.json()["id"]
    assert money(order.json()["total"]) == money("250.00")
    # the failed attempts reserved nothing; the good one reserved everything
    c.as_user("test-admin", {"admin"})
    assert {x["name"]: x["stock_qty"] for x in c.get("/shop/products").json()} == {
        "Krem": 0,
        "Serum": 0,
    }

    # another client can neither see nor cancel it
    _link_client(c, other, "sub-inna")
    assert c.get("/klient/me/orders").json() == []
    assert c.post(f"/klient/me/orders/{oid}/cancel").status_code == 404

    _link_staff(c, julia, "sub-julia")
    assert [o["client_name"] for o in c.get("/shop/orders").json()] == ["Ewa Nowak"]
    assert c.post(f"/shop/orders/{oid}/ready").json()["status"] == "ready"
    c.as_user("sub-ewa", {"client"})
    assert c.post(f"/klient/me/orders/{oid}/cancel").status_code == 409  # already prepared

    c.as_user("sub-julia", {"staff"})
    done = c.post(f"/shop/orders/{oid}/pickup", json={"payment_method": "gotowka"}).json()
    assert done["status"] == "picked_up"
    assert c.post(f"/shop/orders/{oid}/pickup", json={}).status_code == 409  # not twice
    sales = c.get(f"/shop/sales?month={done['created_at'][:7]}").json()
    assert sorted(money(s["total"]) for s in sales) == [money("50"), money("200")]
    assert {s["employee_id"] for s in sales} == {julia} and {s["order_id"] for s in sales} == {oid}
    c.as_user("test-admin", {"admin"})
    # pickup must not take the stock a second time
    assert {x["name"]: x["stock_qty"] for x in c.get("/shop/products").json()} == {
        "Krem": 0,
        "Serum": 0,
    }


def test_cancelled_order_releases_the_stock(portal_client: TestClient) -> None:
    c = portal_client
    p = _product(c, "Krem", "100.00", 2)
    cid = c.post("/clients", json={"first_name": "Ewa", "last_name": "Nowak"}).json()["id"]
    _link_client(c, cid, "sub-ewa")
    oid = c.post("/klient/me/orders", json={"items": [{"product_id": p["id"], "qty": 2}]}).json()[
        "id"
    ]
    assert c.post(f"/klient/me/orders/{oid}/cancel").json()["status"] == "cancelled"
    assert c.post(f"/klient/me/orders/{oid}/cancel").status_code == 409
    c.as_user("test-admin", {"admin"})
    assert c.get("/shop/products").json()[0]["stock_qty"] == 2
    assert c.post(f"/shop/orders/{oid}/pickup", json={}).status_code == 409


def test_shop_is_closed_to_clients_and_catalog_to_anonymous_roles(
    portal_client: TestClient,
) -> None:
    c = portal_client
    _product(c)
    c.as_user("some-client", {"client"})
    assert c.get("/shop/products").status_code == 403
    assert c.post("/shop/sales", json={"product_id": 1}).status_code == 403
    assert c.get("/klient/shop/products").status_code == 200  # browsing needs no profile link
    assert c.get("/klient/me/orders").status_code == 403  # ordering does
    c.as_user("some-staff", {"staff"})
    assert c.get("/klient/shop/products").status_code == 403


def test_shop_sales_count_as_expected_fiscal_takings(db_client: TestClient) -> None:
    """A product sold in the app is rung up on the register but unknown to Booksy —
    it must not show up as a fiscal gap."""
    c = db_client
    day = "2026-09-18"
    p = _product(c, "Krem", "120.00", 5)
    c.post("/shop/sales", json={"product_id": p["id"], "sold_on": day, "payment_method": "karta"})
    c.post("/shop/sales", json={"product_id": p["id"], "sold_on": day, "payment_method": "inne"})
    c.put(f"/salon-days/{day}", json={"booksy_cash": "0", "fiscal_register": "300",
                                      "fiscal_printer_total": "420"})  # fmt: skip
    rec = c.get(f"/salon-days/{day}/reconciliation").json()
    assert money(rec["shop_sales"]) == money("120")  # 'inne' (e.g. a gift) isn't fiscal
    assert rec["status"] == "ok" and money(rec["gap"]) == 0
    month = c.get("/salon-days/reconciliation?month=2026-09").json()
    assert [(d["status"], money(d["shop_sales"])) for d in month] == [("ok", money("120"))]


# ------------------------------------------------------------ review regressions
def _backdate_sale(c: TestClient, sale_id: int, day: str) -> None:
    from datetime import date

    from sqlalchemy import update

    from app.deps import get_db
    from app.models import ProductSale

    db = next(c.app.dependency_overrides[get_db]())
    db.execute(
        update(ProductSale).where(ProductSale.id == sale_id).values(sold_on=date.fromisoformat(day))
    )
    db.commit()


def test_staff_cannot_choose_the_month_their_commission_lands_in(portal_client: TestClient) -> None:
    """The sales commission is a cliff at 1500 zł, so the DATE of a sale is money."""
    from datetime import date

    c = portal_client
    p = _product(c, stock=10)
    julia = _employee(c, "Julia")
    _link_staff(c, julia, "sub-julia")
    today = date.today().isoformat()

    # staff: whatever date the body carries, the sale is dated today
    s = c.post("/shop/sales", json={"product_id": p["id"], "sold_on": "2027-01-15"}).json()
    assert s["sold_on"] == today
    # …and she may void her slip of TODAY, but not an older sale (void + re-enter later)
    old = c.post("/shop/sales", json={"product_id": p["id"]}).json()
    _backdate_sale(c, old["id"], "2026-08-30")
    assert c.delete(f"/shop/sales/{old['id']}").status_code == 403
    assert c.delete(f"/shop/sales/{s['id']}").status_code == 204

    # admin may back-date a forgotten sale, never post-date one
    c.as_user("test-admin", {"admin"})
    assert (
        c.post(
            "/shop/sales",
            json={"product_id": p["id"], "employee_id": julia, "sold_on": "2026-08-20"},
        ).status_code
        == 201
    )
    assert (
        c.post("/shop/sales", json={"product_id": p["id"], "sold_on": "2099-01-01"}).status_code
        == 400
    )


def test_closed_settlement_month_freezes_its_sales(db_client: TestClient) -> None:
    """A closed period is a paid, frozen snapshot: a sale added to it would never be
    paid, one removed from it could be re-entered elsewhere and paid twice."""
    c = db_client
    p = _product(c, stock=10)
    julia = _employee(c, "Julia")
    sale = c.post(
        "/shop/sales", json={"product_id": p["id"], "employee_id": julia, "sold_on": "2026-08-10"}
    ).json()
    c.post("/settlement/periods", json={"year_month": "2026-08"})
    c.post(f"/settlement/periods/2026-08/lines/{julia}/derive")
    assert c.post("/settlement/periods/2026-08/close").status_code == 200

    assert c.delete(f"/shop/sales/{sale['id']}").status_code == 409
    assert (
        c.post(
            "/shop/sales",
            json={"product_id": p["id"], "employee_id": julia, "sold_on": "2026-08-11"},
        ).status_code
        == 409
    )
    assert c.get("/shop/products").json()[0]["stock_qty"] == 9  # nothing moved


def test_settlement_put_without_shop_sales_keeps_the_derived_value(db_client: TestClient) -> None:
    c = db_client
    p = _product(c, "Zestaw", "800.00", 5)
    julia = _employee(c, "Julia")
    for d in ("2026-09-10", "2026-09-11"):
        c.post("/shop/sales", json={"product_id": p["id"], "employee_id": julia, "sold_on": d})
    c.post("/settlement/periods", json={"year_month": "2026-09"})
    c.post(f"/settlement/periods/2026-09/lines/{julia}/derive")
    # the pre-shop panel payload: one edited cell, no shop_sales key at all
    line = c.put(f"/settlement/periods/2026-09/lines/{julia}", json={"hours": "10"}).json()
    assert money(line["shop_sales"]) == money("1600") and money(line["sales_commission"]) == money(
        "160"
    )


def test_staff_do_not_learn_colleagues_sales_from_the_stock_history(
    portal_client: TestClient,
) -> None:
    c = portal_client
    p = _product(c, stock=10)
    julia, ola = _employee(c, "Julia"), _employee(c, "Ola")
    _link_staff(c, julia, "sub-julia")
    _link_staff(c, ola, "sub-ola")
    c.as_user("sub-julia", {"staff"})
    c.post("/shop/sales", json={"product_id": p["id"], "qty": 2})

    c.as_user("sub-ola", {"staff"})
    names = {
        m["reason"]: m["created_by_name"]
        for m in c.get(f"/shop/products/{p['id']}/movements").json()
    }
    assert names == {"sale": None, "delivery": None}  # she sees the shelf, not who sold
    c.as_user("sub-julia", {"staff"})
    mine = {
        m["reason"]: m["created_by_name"]
        for m in c.get(f"/shop/products/{p['id']}/movements").json()
    }
    assert mine["sale"] == "Julia"
    c.as_user("test-admin", {"admin"})
    admin = {
        m["reason"]: m["created_by_name"]
        for m in c.get(f"/shop/products/{p['id']}/movements").json()
    }
    assert admin == {"sale": "Julia", "delivery": "test-admin"}


def test_product_rename_is_checked_and_null_is_not_a_crash(db_client: TestClient) -> None:
    c = db_client
    a, b = _product(c, "Krem"), _product(c, "Serum")
    assert c.patch(f"/shop/products/{b['id']}", json={"name": " KREM "}).status_code == 409
    assert (
        c.patch(f"/shop/products/{a['id']}", json={"name": "krem"}).json()["name"] == "krem"
    )  # own name
    same = c.patch(
        f"/shop/products/{a['id']}", json={"name": None, "price_pln": None, "brand": None}
    )
    assert same.status_code == 200 and same.json()["name"] == "krem"
    assert money(same.json()["price_pln"]) == money("120.00")


def test_client_never_learns_the_stock_figure_and_leaves_no_name_behind(
    portal_client: TestClient,
) -> None:
    c = portal_client
    p = _product(c, "Krem", "100.00", 2)
    cid = c.post("/clients", json={"first_name": "Ewa", "last_name": "Nowakowska"}).json()["id"]
    _link_client(c, cid, "sub-ewa")
    refused = c.post("/klient/me/orders", json={"items": [{"product_id": p["id"], "qty": 3}]})
    assert refused.status_code == 409 and not any(ch.isdigit() for ch in refused.json()["detail"])
    oid = c.post("/klient/me/orders", json={"items": [{"product_id": p["id"], "qty": 2}]}).json()[
        "id"
    ]

    c.as_user("test-admin", {"admin"})
    moves = c.get(f"/shop/products/{p['id']}/movements").json()
    assert moves[0]["reason"] == "order" and moves[0]["created_by_name"] == "klientka (portal)"
    assert "Nowakowska" not in str(moves) and "sub-ewa" not in str(moves)

    # RODO erase with the order still open: her order goes, the 2 items come BACK
    assert c.post(f"/clients/{cid}/erase").status_code == 200
    assert c.get("/shop/products").json()[0]["stock_qty"] == 2
    assert c.get("/shop/orders").json() == []
    moves = c.get(f"/shop/products/{p['id']}/movements").json()
    assert sum(m["delta"] for m in moves) == 2 and moves[0]["ref"] == f"order:{oid}"
    assert "Nowakowska" not in str(moves)


def test_voiding_a_pickup_sale_puts_the_item_back(portal_client: TestClient) -> None:
    c = portal_client
    p = _product(c, "Krem", "100.00", 1)
    cid = c.post("/clients", json={"first_name": "Ewa", "last_name": "Nowak"}).json()["id"]
    _link_client(c, cid, "sub-ewa")
    oid = c.post("/klient/me/orders", json={"items": [{"product_id": p["id"], "qty": 1}]}).json()[
        "id"
    ]
    c.as_user("test-admin", {"admin"})
    done = c.post(f"/shop/orders/{oid}/pickup", json={}).json()
    sale = c.get(f"/shop/sales?month={done['created_at'][:7]}").json()[0]
    assert c.get("/shop/products").json()[0]["stock_qty"] == 0
    assert c.delete(f"/shop/sales/{sale['id']}").status_code == 204
    assert c.get("/shop/products").json()[0]["stock_qty"] == 1  # reserved at order, back at void


def test_shop_turnover_reaches_the_pnl_and_the_kasa_summary(db_client: TestClient) -> None:
    """Products sold in the app never pass through Booksy — without this the whole
    shop turnover is missing from revenue while its costs are already counted."""
    c = db_client
    p = _product(c, "Zestaw", "500.00", 9)
    for method in ("karta", "gotowka", "inne"):
        c.post("/shop/sales", json={"product_id": p["id"], "sold_on": "2026-09-10",
                                    "payment_method": method})  # fmt: skip
    c.put("/salon-days/2026-09-10", json={"booksy_cash": "100", "fiscal_register": "300"})
    pnl = c.get("/pnl/2026-09").json()
    assert pnl["revenue_source"] == "computed" and money(pnl["revenue"]) == money(
        "1300"
    )  # 300 + 2×500
    kasa = c.get("/salon-days/summary?month=2026-09").json()
    assert money(kasa["shop_sales"]) == money("1000") and money(kasa["money_total"]) == money(
        "1300"
    )
