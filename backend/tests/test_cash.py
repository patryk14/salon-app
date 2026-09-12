"""Daily cash reconciliation (salon_day): derived unregistered cash + typed
Booksy/fiscal totals, admin-only."""

from decimal import Decimal

from fastapi.testclient import TestClient

from tests.test_settlement import _emp


def _cash(c: TestClient, emp: int, day: str, amount: str) -> None:
    r = c.post(
        "/ledger",
        json={"employee_id": emp, "entry_date": day, "service_name": "X", "amount_pln": amount},
    )
    assert r.status_code == 201, r.text


def test_salon_day_reconciliation(db_client: TestClient) -> None:
    e1 = _emp(db_client, "A")
    e2 = _emp(db_client, "B")

    # Nothing entered yet: everything zero, no row needed.
    r = db_client.get("/salon-days/2026-09-15").json()
    assert Decimal(str(r["unregistered_cash"])) == 0
    assert Decimal(str(r["cash_in_register"])) == 0

    # Ledger cash on the day (two employees) + one on another day (must not leak).
    _cash(db_client, e1, "2026-09-15", "150")
    _cash(db_client, e2, "2026-09-15", "80")
    _cash(db_client, e1, "2026-09-16", "999")

    r = db_client.get("/salon-days/2026-09-15").json()
    assert Decimal(str(r["unregistered_cash"])) == Decimal("230")  # 150 + 80, not the 999

    # Type Booksy cash + fiscal register.
    r = db_client.put(
        "/salon-days/2026-09-15",
        json={"booksy_cash": "500", "fiscal_register": "3600", "note": "ok"},
    ).json()
    assert Decimal(str(r["booksy_cash"])) == 500
    assert Decimal(str(r["fiscal_register"])) == 3600
    assert Decimal(str(r["cash_in_register"])) == Decimal("730")  # 230 + 500
    assert r["note"] == "ok"

    # Persisted, and unregistered still derived (add more cash → it grows).
    _cash(db_client, e2, "2026-09-15", "20")
    r = db_client.get("/salon-days/2026-09-15").json()
    assert Decimal(str(r["unregistered_cash"])) == Decimal("250")
    assert Decimal(str(r["cash_in_register"])) == Decimal("750")  # 250 + 500 kept


def test_salon_day_admin_only(portal_client: TestClient) -> None:
    portal_client.as_user("staff-sub", {"staff"})
    assert portal_client.get("/salon-days/2026-09-15").status_code == 403
    assert portal_client.put("/salon-days/2026-09-15", json={"booksy_cash": "1"}).status_code == 403
