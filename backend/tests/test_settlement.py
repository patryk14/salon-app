"""Settlement workflow: employees → draft period → enter numbers → close.

Uses db_client (in-memory SQLite, auth overridden to admin). Employees are
created via the API here — the migration's seeded roster only exists against
real Postgres, not the create_all test schema.
"""

from decimal import Decimal

from fastapi.testclient import TestClient


def money(value) -> Decimal:
    """Compare money by value, not string form: SQLite drops Numeric scale
    ('14150'), Postgres keeps it ('14150.00'). Both parse to the same Decimal."""
    return Decimal(str(value))


def _emp(db_client: TestClient, name: str, fte: str = "1.0", pay_type: str = "hourly") -> int:
    r = db_client.post(
        "/employees", json={"display_name": name, "fte_factor": fte, "pay_type": pay_type}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_full_period_klaudia_and_hania(db_client: TestClient) -> None:
    klaudia = _emp(db_client, "Klaudia", "1.0", "uop_plus_extra")
    hania = _emp(db_client, "Hania", "0.5")

    assert db_client.post("/settlement/periods", json={"year_month": "2026-09"}).status_code == 201

    # Klaudia: 14150 services (Booksy+zeszyt+gotówka), 70 sales, 10h → 1729
    r = db_client.put(
        "/settlement/periods/2026-09/lines/" + str(klaudia),
        json={
            "booksy_services": "10415",
            "notebook_services": "400",
            "cash_services": "3335",
            "booksy_sales": "70",
            "hours": "10",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert money(body["services_base"]) == money("14150")
    assert money(body["services_rate"]) == money("0.100")
    assert money(body["total_payout"]) == money("1729")

    # Hania: 3355 services @ 0.5 fte → 6% → 201.30 → ceil 202 (NOT the sheet's 234.85)
    r = db_client.put(
        "/settlement/periods/2026-09/lines/" + str(hania),
        json={"booksy_services": "2410", "notebook_services": "310", "cash_services": "635"},
    )
    assert money(r.json()["services_commission"]) == money("201.30")
    assert money(r.json()["total_payout"]) == money("202")

    period = db_client.get("/settlement/periods/2026-09").json()
    assert period["status"] == "draft"
    assert len(period["lines"]) == 2


def test_reentering_numbers_recomputes(db_client: TestClient) -> None:
    e = _emp(db_client, "Oliwia")
    db_client.post("/settlement/periods", json={"year_month": "2026-09"})
    url = f"/settlement/periods/2026-09/lines/{e}"

    db_client.put(url, json={"booksy_services": "5000"})  # below floor → 0
    line = db_client.get("/settlement/periods/2026-09").json()["lines"][0]
    assert money(line["total_payout"]) == money("0")

    # Oliwia's real 15164 → new 12% bracket → 1819.68 → 1820
    r = db_client.put(
        url, json={"booksy_services": "12584", "notebook_services": "360", "cash_services": "2220"}
    )
    assert money(r.json()["services_rate"]) == money("0.120")
    assert money(r.json()["total_payout"]) == money("1820")
    # still one line, not two
    assert len(db_client.get("/settlement/periods/2026-09").json()["lines"]) == 1


def test_close_freezes_period(db_client: TestClient) -> None:
    e = _emp(db_client, "Karola")
    db_client.post("/settlement/periods", json={"year_month": "2026-09"})
    db_client.put(f"/settlement/periods/2026-09/lines/{e}", json={"booksy_services": "13149"})

    closed = db_client.post("/settlement/periods/2026-09/close")
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"

    # no more edits once closed
    late = db_client.put(
        f"/settlement/periods/2026-09/lines/{e}", json={"booksy_services": "99999"}
    )
    assert late.status_code == 409
    # second close is rejected
    assert db_client.post("/settlement/periods/2026-09/close").status_code == 409


def test_override_recorded(db_client: TestClient) -> None:
    e = _emp(db_client, "Julia", "0.75")  # historical 0.75 → 5689 lands at 7% → 399
    db_client.post("/settlement/periods", json={"year_month": "2026-09"})
    r = db_client.put(
        f"/settlement/periods/2026-09/lines/{e}",
        json={
            "booksy_services": "4540",
            "notebook_services": "1149",
            "override_total": "450",
            "override_reason": "bonus uznaniowy",
        },
    )
    body = r.json()
    assert money(body["total_payout"]) == money("399")  # computed value is still stored...
    assert money(body["override_total"]) == money("450")  # ...and the override sits alongside it
    assert body["override_reason"] == "bonus uznaniowy"


def test_duplicate_period_conflicts(db_client: TestClient) -> None:
    db_client.post("/settlement/periods", json={"year_month": "2026-09"})
    assert db_client.post("/settlement/periods", json={"year_month": "2026-09"}).status_code == 409


def test_bad_year_month_rejected(db_client: TestClient) -> None:
    assert db_client.post("/settlement/periods", json={"year_month": "2026-13"}).status_code == 422
    assert db_client.post("/settlement/periods", json={"year_month": "nope"}).status_code == 422


def test_line_on_missing_period_404(db_client: TestClient) -> None:
    e = _emp(db_client, "Ktoś")
    assert db_client.put(f"/settlement/periods/2099-01/lines/{e}", json={}).status_code == 404


def test_decision_log_append_and_list(db_client: TestClient) -> None:
    r = db_client.post(
        "/commission/decisions",
        json={"decided_on": "2026-09-07", "topic": "Test", "ruling": "R", "decided_by": "wl"},
    )
    assert r.status_code == 201
    assert any(d["topic"] == "Test" for d in db_client.get("/commission/decisions").json())


# ------------------------------------------------------------------ aliases
def test_alias_add_list_remove(db_client: TestClient) -> None:
    e = _emp(db_client, "Karola")
    r = db_client.post(f"/employees/{e}/aliases", json={"alias": " Karolina "})
    assert r.status_code == 201, r.text
    alias_id = r.json()["id"]
    assert r.json()["alias"] == "Karolina"  # trimmed

    emp = next(x for x in db_client.get("/employees").json() if x["id"] == e)
    assert [a["alias"] for a in emp["aliases"]] == ["Karolina"]

    assert db_client.delete(f"/employees/{e}/aliases/{alias_id}").status_code == 204
    emp = next(x for x in db_client.get("/employees").json() if x["id"] == e)
    assert emp["aliases"] == []


def test_alias_globally_unique(db_client: TestClient) -> None:
    a = _emp(db_client, "Ala")
    b = _emp(db_client, "Bea")
    assert db_client.post(f"/employees/{a}/aliases", json={"alias": "Alicja"}).status_code == 201
    # same name cannot map to a second employee
    assert db_client.post(f"/employees/{b}/aliases", json={"alias": "Alicja"}).status_code == 409


def test_alias_on_missing_employee_404(db_client: TestClient) -> None:
    assert db_client.post("/employees/9999/aliases", json={"alias": "X"}).status_code == 404


def test_remove_alias_wrong_employee_404(db_client: TestClient) -> None:
    a = _emp(db_client, "Ala")
    b = _emp(db_client, "Bea")
    alias_id = db_client.post(f"/employees/{a}/aliases", json={"alias": "Alicja"}).json()["id"]
    # alias belongs to a, not b
    assert db_client.delete(f"/employees/{b}/aliases/{alias_id}").status_code == 404


def test_unmatched_staff_lists_names_without_alias(db_client: TestClient) -> None:
    from tests.test_worklog import _visit

    e = _emp(db_client, "Karola")
    db_client.post(f"/employees/{e}/aliases", json={"alias": "Karolina"})
    _visit(db_client, "Karolina", "2026-09-03", "200")  # matched → not listed
    _visit(db_client, "Nowa Osoba", "2026-09-04", "150")  # no alias → listed

    unmatched = db_client.get("/employees/unmatched-staff", params={"month": "2026-09"}).json()
    assert unmatched == ["Nowa Osoba"]
