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


def _visit(
    db_client: TestClient, staff_name: str, day: str, price: str, status: str = "Zakończone"
):
    """Create a completed visit via the Booksy import (the only way visits get
    staff_name set) — a synthetic one-row report."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Lista wizyt"
    for _ in range(7):
        ws.append([])
    ws.append(
        [
            None,
            "Data i godzina",
            "ID rezerwacji",
            "Kategoria",
            "Usługa",
            "Klient",
            "Pracownik",
            "Czas",
            "Wartość",
            "Dodatki",
            "Netto",
            "Rabat",
            "Podatek",
            "Napiwek",
            "Przychód",
            "Status",
        ]
    )
    d = day.split("-")
    ws.append(
        [
            None,
            f"{d[2]}.{d[1]}.{d[0]} 10:00",
            str(hash(day + staff_name) % 10**7),
            "Kat",
            "Usługa",
            "Klientka X",
            staff_name,
            "01h",
            price,
            0,
            price,
            0,
            0,
            0,
            price,
            status,
        ]
    )
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = db_client.post(
        "/imports/booksy/visits",
        files={"file": ("w.xlsx", buf, "application/vnd.ms-excel")},
    )
    assert r.status_code == 200, r.text


def test_derive_assembles_all_three_sources(db_client: TestClient) -> None:
    # Hania resolves 'Hanna' Booksy visits; hours from timesheets; cash from ledger.
    r = db_client.post(
        "/employees", json={"display_name": "Hania", "fte_factor": "0.5", "aliases": ["Hanna"]}
    )
    e = r.json()["id"]
    _visit(db_client, "Hanna", "2026-09-10", "2410")  # Booksy services 2410
    for day, h in (("2026-09-01", "5"), ("2026-09-02", "5"), ("2026-09-03", "5")):
        db_client.post("/timesheets", json={"employee_id": e, "work_date": day, "hours": h})
    for amt in ("600", "35"):
        db_client.post(
            "/ledger", json={"employee_id": e, "entry_date": "2026-09-04", "amount_pln": amt}
        )

    db_client.post("/settlement/periods", json={"year_month": "2026-09"})
    r = db_client.post(f"/settlement/periods/2026-09/lines/{e}/derive")
    assert r.status_code == 200, r.text
    line = r.json()
    assert money(line["booksy_services"]) == money("2410")  # DERIVED from visits
    assert money(line["cash_services"]) == money("635")  # DERIVED from ledger
    assert money(line["hours"]) == money("15")  # DERIVED from timesheets
    # 2410 + 635 = 3045 services, hania 0.5 → ≥3000 → 6% → 182.70; hours 15*31.40=471
    assert money(line["services_base"]) == money("3045")
    assert money(line["services_commission"]) == money("182.70")
    assert money(line["hours_pay"]) == money("471.00")
    assert money(line["total_payout"]) == money("654")  # ceil(182.70 + 471.00)


def test_derive_all_builds_the_whole_period(db_client: TestClient) -> None:
    r = db_client.post("/employees", json={"display_name": "Karola", "aliases": ["Karolina"]})
    karola = r.json()["id"]
    _emp(db_client, "Oliwia")
    _visit(db_client, "Karolina", "2026-09-05", "13149")

    db_client.post("/settlement/periods", json={"year_month": "2026-09"})
    period = db_client.post("/settlement/periods/2026-09/derive-all").json()
    assert period["status"] == "draft"
    assert len(period["lines"]) == 2  # every active employee gets a line
    karola_line = next(x for x in period["lines"] if x["employee_id"] == karola)
    assert money(karola_line["booksy_services"]) == money("13149")
    assert money(karola_line["services_rate"]) == money("0.100")  # ≥10000 → 10%


def test_readiness_flags_empty_and_unmatched(db_client: TestClient) -> None:
    r = db_client.post("/employees", json={"display_name": "Karola", "aliases": ["Karolina"]})
    karola = r.json()["id"]
    _visit(db_client, "Karolina", "2026-09-05", "13149")
    _visit(db_client, "Nieznana Pracownica", "2026-09-06", "500")  # no alias → unmatched

    db_client.post("/settlement/periods", json={"year_month": "2026-09"})
    db_client.post("/settlement/periods/2026-09/derive-all")
    rd = db_client.get("/settlement/periods/2026-09/readiness").json()
    assert rd["ok"] is False
    kinds = {w["kind"] for w in rd["warnings"]}
    assert "unmatched_staff" in kinds  # dropped Booksy revenue is surfaced
    # Karola has revenue → not flagged empty
    assert not any(w["employee"] == "Karola" and w["kind"] == "empty" for w in rd["warnings"])


def test_worklog_endpoints_require_admin(auth_client: TestClient, mint_token) -> None:
    staff = {"Authorization": f"Bearer {mint_token(groups=['staff'])}"}
    assert auth_client.get("/timesheets", headers=staff).status_code == 403
    assert auth_client.get("/ledger", headers=staff).status_code == 403
