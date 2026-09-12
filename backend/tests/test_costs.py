"""zabiegi_koszty cash import: per-employee cash → ledger, reconciliation rows
→ salon_day, name resolution via aliases, month-scoped and idempotent."""

import io
from decimal import Decimal

from fastapi.testclient import TestClient
from openpyxl import Workbook


def _emp_alias(c: TestClient, name: str, alias: str) -> int:
    r = c.post("/employees", json={"display_name": name, "aliases": [alias]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sheet() -> io.BytesIO:
    """A minimal zabiegi_koszty sheet: 2 employees + 1 unknown + reconciliation."""
    wb = Workbook()
    ws = wb.active
    ws.append(["", *range(1, 32)])  # header: leading "" then day columns 1..31

    def row(label, vals: dict[int, object]):
        r = [label] + [""] * 31
        for day, v in vals.items():
            r[day] = v  # column index == day (header shifted by the leading "")
        ws.append(r)

    row("Karolina", {})
    row("Zabieg 1", {3: 80, 4: 200})
    row("SUMA Karolina", {3: 80, 4: 200})
    row("Oliwia", {})
    row("Zabieg 1", {2: 150, 5: 220})
    row("Suma Oliwia", {2: 150, 5: 220})
    row("Nieznana", {})  # no alias → unmatched, its cash dropped
    row("Zabieg 1", {2: 999})
    row("Gotowka nie wbita", {2: 150, 3: 80, 4: 200, 5: 220})  # matches matched employees
    row("Gotowka z booksy", {2: 265, 3: 200})
    row("Kasa fiskalna", {2: 3600, 3: 3995})
    row("Suma", {2: 3750})
    row("OPIS", {})
    row("Kolumny od 1 do 31 oznaczaja dni miesiaca.", {})
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _import(c: TestClient, ym: str = "2026-09"):
    return c.post(
        "/imports/costs",
        data={"year_month": ym},
        files={"file": ("k.xlsx", _sheet(), "application/vnd.ms-excel")},
    )


def test_costs_import_maps_cash_and_reconciliation(db_client: TestClient) -> None:
    karola = _emp_alias(db_client, "Karola", "Karolina")
    oliwia = _emp_alias(db_client, "Oliwia", "Oliwia")

    r = _import(db_client)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["ledger_created"] == 4  # Karola d3,d4 + Oliwia d2,d5
    assert s["salon_days_created"] == 2  # days 2 and 3
    assert s["per_employee"]["Karola"] == "280"
    assert s["per_employee"]["Oliwia"] == "370"
    assert s["unmatched_names"] == ["Nieznana"]  # "Nieznana" cash dropped, flagged
    assert s["checksum_ok"] is True

    # Cash lands in the ledger, resolved to the right employees.
    kar = db_client.get("/ledger", params={"employee_id": karola, "month": "2026-09"}).json()
    assert sum(Decimal(str(e["amount_pln"])) for e in kar) == Decimal("280")
    oli = db_client.get("/ledger", params={"employee_id": oliwia, "month": "2026-09"}).json()
    assert sum(Decimal(str(e["amount_pln"])) for e in oli) == Decimal("370")

    # Reconciliation lands in salon_day; unregistered is derived from the ledger.
    sd = db_client.get("/salon-days/2026-09-02").json()
    assert Decimal(str(sd["booksy_cash"])) == 265
    assert Decimal(str(sd["fiscal_register"])) == 3600
    assert Decimal(str(sd["unregistered_cash"])) == 150  # Oliwia d2 only (Nieznana dropped)
    assert Decimal(str(sd["cash_in_register"])) == Decimal("415")  # 150 + 265


def test_costs_import_replaces_month(db_client: TestClient) -> None:
    _emp_alias(db_client, "Karola", "Karolina")
    _emp_alias(db_client, "Oliwia", "Oliwia")
    assert _import(db_client).json()["ledger_created"] == 4
    # Re-import the same month: replaces, does not duplicate.
    assert _import(db_client).json()["ledger_created"] == 4
    total = db_client.get("/ledger", params={"month": "2026-09"}).json()
    assert len(total) == 4


def test_costs_import_admin_only(portal_client: TestClient) -> None:
    portal_client.as_user("staff-sub", {"staff"})
    r = portal_client.post(
        "/imports/costs",
        data={"year_month": "2026-09"},
        files={"file": ("k.xlsx", _sheet(), "application/vnd.ms-excel")},
    )
    assert r.status_code == 403
