"""Timesheets, ledger, and deriving a settlement line from them (F3)."""

from decimal import Decimal

from fastapi.testclient import TestClient


def money(v) -> Decimal:
    return Decimal(str(v))


def _emp(db_client: TestClient, name: str, fte: str = "1.0") -> int:
    r = db_client.post("/employees", json={"display_name": name, "fte_factor": fte})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_timesheet_upsert_and_month_filter(db_client: TestClient) -> None:
    e = _emp(db_client, "Klaudia")
    db_client.post("/timesheets", json={"employee_id": e, "work_date": "2026-09-01", "hours": "6"})
    # same day again → overwrite, not duplicate
    db_client.post("/timesheets", json={"employee_id": e, "work_date": "2026-09-01", "hours": "8"})
    db_client.post("/timesheets", json={"employee_id": e, "work_date": "2026-09-02", "hours": "4"})
    db_client.post("/timesheets", json={"employee_id": e, "work_date": "2026-10-01", "hours": "5"})

    sept = db_client.get("/timesheets", params={"employee_id": e, "month": "2026-09"}).json()
    assert len(sept) == 2  # Oct excluded
    assert money(sept[0]["hours"]) == money("8")  # overwritten value


def test_ledger_accumulates_per_month(db_client: TestClient) -> None:
    e = _emp(db_client, "Oliwia")
    for amt in ("100.50", "200", "50.50"):
        db_client.post(
            "/ledger", json={"employee_id": e, "entry_date": "2026-09-10", "amount_pln": amt}
        )
    rows = db_client.get("/ledger", params={"employee_id": e, "month": "2026-09"}).json()
    assert len(rows) == 3  # multiple cash entries per day allowed


def test_derive_pulls_hours_and_cash_into_settlement(db_client: TestClient) -> None:
    e = _emp(db_client, "Hania", "0.5")
    # 3 days of hours = 15h total; two cash services = 635 total.
    for day, h in (("2026-09-01", "5"), ("2026-09-02", "5"), ("2026-09-03", "5")):
        db_client.post("/timesheets", json={"employee_id": e, "work_date": day, "hours": h})
    db_client.post(
        "/ledger", json={"employee_id": e, "entry_date": "2026-09-04", "amount_pln": "600"}
    )
    db_client.post(
        "/ledger", json={"employee_id": e, "entry_date": "2026-09-05", "amount_pln": "35"}
    )

    db_client.post("/settlement/periods", json={"year_month": "2026-09"})
    # seed the Booksy/notebook part manually first
    db_client.put(
        f"/settlement/periods/2026-09/lines/{e}",
        json={"booksy_services": "2410", "notebook_services": "310"},
    )
    # now derive hours + cash from F3 sources
    r = db_client.post(f"/settlement/periods/2026-09/lines/{e}/derive")
    assert r.status_code == 200, r.text
    line = r.json()
    assert money(line["hours"]) == money("15")
    assert money(line["cash_services"]) == money("635")
    # 2410 + 310 + 635 = 3355 services, hania 0.5 → 6% → 201.30; hours 15*31.40=471
    assert money(line["services_base"]) == money("3355")
    assert money(line["services_commission"]) == money("201.30")
    assert money(line["hours_pay"]) == money("471.00")
    assert money(line["total_payout"]) == money("673")  # ceil(201.30 + 471.00)


def test_derive_preserves_booksy_and_recomputes_on_new_entries(db_client: TestClient) -> None:
    e = _emp(db_client, "Karola")
    db_client.post("/settlement/periods", json={"year_month": "2026-09"})
    db_client.put(f"/settlement/periods/2026-09/lines/{e}", json={"booksy_services": "13149"})

    db_client.post("/timesheets", json={"employee_id": e, "work_date": "2026-09-01", "hours": "10"})
    r = db_client.post(f"/settlement/periods/2026-09/lines/{e}/derive")
    line = r.json()
    assert money(line["booksy_services"]) == money("13149")  # preserved
    assert money(line["hours"]) == money("10")  # derived
    assert money(line["hours_pay"]) == money("314.00")


def test_worklog_endpoints_require_admin(auth_client: TestClient, mint_token) -> None:
    staff = {"Authorization": f"Bearer {mint_token(groups=['staff'])}"}
    assert auth_client.get("/timesheets", headers=staff).status_code == 403
    assert auth_client.get("/ledger", headers=staff).status_code == 403
