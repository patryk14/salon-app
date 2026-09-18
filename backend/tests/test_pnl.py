"""Monthly P&L (F12) — the formula is pinned to the owner's real sheet, which
reconciles to the złoty: operating 24250, staff 19260 → costs 43510; revenue
52758 → profit 9248. Derived inputs (kasa revenue, settlement staff cost) and
the draft→closed freeze are exercised end-to-end through the API."""

from decimal import Decimal

from fastapi.testclient import TestClient

from app.pnl import totals


def money(v) -> Decimal:
    return Decimal(str(v))


def test_totals_reproduces_the_owner_sheet() -> None:
    category_totals = {
        "koszty_stale": Decimal("16472"),
        "koszty_zmienne": Decimal("1732"),
        "koszty_jednorazowe": Decimal("771"),
        "paznokcie": Decimal("2342"),
        "kosmetologia": Decimal("2933"),
        "kosmetyki_odsprzedaz": Decimal("0"),
    }
    t = totals(Decimal("52758"), category_totals, Decimal("19260"))
    assert t.operating_total == Decimal("24250")  # KOSZTY ŁĄCZNE
    assert t.staff_cost == Decimal("19260")  # KOSZT PRACOWNICY
    assert t.costs_total == Decimal("43510")  # PODSUMOWANIE KOSZTÓW
    assert t.profit == Decimal("9248")  # ZAROBEK


def test_categories_are_seeded(db_client: TestClient) -> None:
    cats = db_client.get("/expenses/categories").json()
    assert [c["code"] for c in cats] == [
        "koszty_stale",
        "koszty_zmienne",
        "koszty_jednorazowe",
        "paznokcie",
        "kosmetologia",
        "kosmetyki_odsprzedaz",
    ]


def test_pnl_requires_admin(portal_client: TestClient) -> None:
    portal_client.as_user("staff-sub", {"staff"})
    assert portal_client.get("/pnl/2026-08").status_code == 403
    assert portal_client.get("/expenses/categories").status_code == 403


def test_month_opens_and_prefills_recurring_once(db_client: TestClient) -> None:
    r = db_client.post(
        "/expenses/recurring",
        json={"category_code": "koszty_stale", "name": "Najem", "amount_pln": "5840"},
    )
    assert r.status_code == 200, r.text

    p = db_client.get("/pnl/2026-08").json()
    stale = next(c for c in p["categories"] if c["code"] == "koszty_stale")
    najem = [line for line in stale["lines"] if line["name"] == "Najem"]
    assert len(najem) == 1
    assert najem[0]["source"] == "recurring"
    assert money(stale["total"]) == money("5840")

    # opening the month again must not duplicate the prefilled line
    p2 = db_client.get("/pnl/2026-08").json()
    stale2 = next(c for c in p2["categories"] if c["code"] == "koszty_stale")
    assert len([line for line in stale2["lines"] if line["name"] == "Najem"]) == 1


def test_pnl_end_to_end_reproduces_sheet(db_client: TestClient) -> None:
    ym = "2026-08"
    db_client.get(f"/pnl/{ym}")  # open month (no recurring seeded → clean slate)
    for code, name, amount in [
        ("koszty_stale", "Suma stałych", "16472"),
        ("koszty_zmienne", "Suma zmiennych", "1732"),
        ("koszty_jednorazowe", "Jednorazowe", "771"),
        ("paznokcie", "Paznokcie", "2342"),
        ("kosmetologia", "Kosmetologia", "2933"),
        ("kosmetyki_odsprzedaz", "Odsprzedaż", "0"),
    ]:
        r = db_client.post(
            "/expenses",
            json={"year_month": ym, "category_code": code, "name": name, "amount_pln": amount},
        )
        assert r.status_code == 200, r.text

    p = db_client.put(
        f"/pnl/{ym}", json={"revenue_override": "52758", "staff_cost_override": "19260"}
    ).json()
    assert p["revenue_source"] == "override"
    assert money(p["revenue"]) == money("52758")
    assert money(p["operating_total"]) == money("24250")
    assert money(p["staff_cost"]) == money("19260")
    assert money(p["costs_total"]) == money("43510")
    assert money(p["profit"]) == money("9248")


def test_derived_revenue_and_staff_cost(db_client: TestClient) -> None:
    ym = "2026-06"
    # revenue: one salon day, kasa fiskalna 1000 (admin passes the staff gate)
    r = db_client.put(f"/salon-days/{ym}-15", json={"fiscal_register": "1000"})
    assert r.status_code == 200, r.text
    # staff cost: a settlement with a 10h line → 10 * 31.40 = 314
    emp = db_client.post("/employees", json={"display_name": "Ola", "fte_factor": "1.0"}).json()[
        "id"
    ]
    db_client.post("/settlement/periods", json={"year_month": ym})
    db_client.put(f"/settlement/periods/{ym}/lines/{emp}", json={"hours": "10"})
    # a DRAFT settlement must NOT drive the P&L — it falls back to the estimate
    assert db_client.get(f"/pnl/{ym}").json()["staff_cost_source"] == "estimate"
    # once CLOSED, the settlement payout is authoritative: 10 h × 31.40 = 314
    assert db_client.post(f"/settlement/periods/{ym}/close").status_code == 200

    p = db_client.get(f"/pnl/{ym}").json()
    assert p["revenue_source"] == "computed"
    assert money(p["revenue"]) == money("1000")
    assert p["staff_cost_source"] == "settlement"
    assert money(p["staff_cost"]) == money("314")
    assert money(p["profit"]) == money("686")  # 1000 - 314, no expenses


def test_staff_cost_breakdown(db_client: TestClient) -> None:
    db_client.post("/employees", json={"display_name": "Ola", "fte_factor": "1.0"})
    e2 = db_client.post(
        "/employees",
        json={"display_name": "Klaudia", "fte_factor": "1.0", "pay_type": "uop_plus_extra"},
    ).json()["id"]

    out = db_client.get("/pnl/2026-09/staff").json()
    assert out["year_month"] == "2026-09"
    rows = {r["name"]: r for r in out["rows"]}
    assert {"Ola", "Klaudia"} <= set(rows)
    assert rows["Klaudia"]["needs_base"] is True  # UoP salary not set yet
    assert rows["Ola"]["needs_base"] is False
    # zlecenie base uses statutory month hours (Sept 2026 = 176 h full-time), not logged
    assert money(rows["Ola"]["hours"]) == money("176")
    assert money(rows["Ola"]["base_cost"]) == money("5526.40")  # 176 × 31.40

    db_client.patch(f"/employees/{e2}", json={"monthly_base_pln": "4300"})
    k = next(
        r for r in db_client.get("/pnl/2026-09/staff").json()["rows"] if r["name"] == "Klaudia"
    )
    assert k["needs_base"] is False
    assert money(k["base_cost"]) == money("4300")  # no hours → base = fixed salary
    assert money(k["breakeven_revenue"]) == money("4300")  # below floor → break-even = base


def test_close_freezes_and_locks_then_reopens(db_client: TestClient) -> None:
    ym = "2026-07"
    db_client.get(f"/pnl/{ym}")
    db_client.post(
        "/expenses",
        json={
            "year_month": ym,
            "category_code": "koszty_zmienne",
            "name": "Reklama",
            "amount_pln": "1000",
        },
    )
    db_client.put(f"/pnl/{ym}", json={"revenue_override": "5000", "staff_cost_override": "2000"})

    closed = db_client.post(f"/pnl/{ym}/close").json()
    assert closed["status"] == "closed"
    assert money(closed["profit"]) == money("2000")  # 5000 - (1000 + 2000)
    assert closed["revenue_source"] == "snapshot"

    # locked: no new lines while closed
    blocked = db_client.post(
        "/expenses",
        json={"year_month": ym, "category_code": "koszty_zmienne", "name": "X", "amount_pln": "1"},
    )
    assert blocked.status_code == 409

    # reopen unlocks editing
    assert db_client.post(f"/pnl/{ym}/reopen").json()["status"] == "draft"
    ok = db_client.post(
        "/expenses",
        json={"year_month": ym, "category_code": "koszty_zmienne", "name": "X", "amount_pln": "1"},
    )
    assert ok.status_code == 200
