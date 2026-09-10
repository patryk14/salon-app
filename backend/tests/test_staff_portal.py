"""F6 staff portal: invite → claim → row-scoped /me. The security-critical part
is the NEGATIVE tests: a staff login must never read another employee's data,
and an unlinked login must be refused.

Uses portal_client (swappable identity over one in-memory DB): act as admin to
create employees/invites, then as a staff `sub` to claim and read.
"""

from decimal import Decimal

from fastapi.testclient import TestClient

from tests.test_worklog import _visit


def _emp(c: TestClient, name: str, fte: str = "1.0") -> int:
    r = c.post("/employees", json={"display_name": name, "fte_factor": fte})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _invite_code(c: TestClient, employee_id: int) -> str:
    r = c.post("/invites", json={"employee_id": employee_id})
    assert r.status_code == 201, r.text
    return r.json()["code"]


def test_claim_binds_sub_to_employee(portal_client: TestClient) -> None:
    c = portal_client
    emp = _emp(c, "Ola")
    code = _invite_code(c, emp)

    c.as_user("ola-sub", {"staff"})
    # Not linked yet — /me works and says so; scoped endpoints are refused.
    who = c.get("/me").json()
    assert who == {
        "linked": False,
        "role": "staff",
        "employee_id": None,
        "display_name": None,
        "fte_factor": None,
        "pay_type": None,
        "is_active": None,
    }
    assert c.get("/me/revenue", params={"month": "2026-09"}).status_code == 403

    r = c.post("/invites/claim", json={"code": code})
    assert r.status_code == 200, r.text
    assert r.json()["linked"] is True
    assert r.json()["employee_id"] == emp

    who = c.get("/me").json()
    assert who["linked"] is True
    assert who["employee_id"] == emp
    assert who["display_name"] == "Ola"


def test_claim_is_single_use_and_sub_unique(portal_client: TestClient) -> None:
    c = portal_client
    emp = _emp(c, "Ola")
    code = _invite_code(c, emp)

    c.as_user("ola-sub", {"staff"})
    assert c.post("/invites/claim", json={"code": code}).status_code == 200
    # same sub cannot claim again (already linked)
    assert c.post("/invites/claim", json={"code": code}).status_code == 409

    # a different sub cannot reuse the already-claimed code
    c.as_user("someone-else", {"staff"})
    assert c.post("/invites/claim", json={"code": code}).status_code == 409


def test_claim_bad_code_404(portal_client: TestClient) -> None:
    portal_client.as_user("x", {"staff"})
    assert portal_client.post("/invites/claim", json={"code": "NOPE"}).status_code == 404


def test_me_revenue_scoped_to_own_visits(portal_client: TestClient) -> None:
    c = portal_client
    ola = _emp(c, "Ola")
    kaia = _emp(c, "Kaia")
    # aliases so Booksy names resolve
    c.post(f"/employees/{ola}/aliases", json={"alias": "Ola"})
    c.post(f"/employees/{kaia}/aliases", json={"alias": "Kaia"})
    _visit(c, "Ola", "2026-09-03", "300")
    _visit(c, "Kaia", "2026-09-03", "999")  # someone else's revenue

    code = _invite_code(c, ola)
    c.as_user("ola-sub", {"staff"})
    c.post("/invites/claim", json={"code": code})

    rev = c.get("/me/revenue", params={"month": "2026-09"}).json()
    assert Decimal(str(rev["booksy_services"])) == Decimal("300")  # only Ola's, never Kaia's
    assert Decimal(str(rev["services_total"])) == Decimal("300")

    visits = c.get("/me/visits", params={"month": "2026-09"}).json()
    assert [v["staff_name"] for v in visits] == ["Ola"]


def test_me_hours_self_entry_and_commission(portal_client: TestClient) -> None:
    c = portal_client
    ola = _emp(c, "Ola")
    code = _invite_code(c, ola)
    c.as_user("ola-sub", {"staff"})
    c.post("/invites/claim", json={"code": code})

    assert c.post("/me/hours", json={"work_date": "2026-09-02", "hours": "8"}).status_code == 201
    # 11 h/day cap applies to self-entry too
    assert c.post("/me/hours", json={"work_date": "2026-09-03", "hours": "12"}).status_code == 422

    hours = c.get("/me/hours", params={"month": "2026-09"}).json()
    assert len(hours) == 1 and Decimal(str(hours[0]["hours"])) == Decimal("8")

    comm = c.get("/me/commission", params={"month": "2026-09"}).json()
    assert Decimal(str(comm["hours"])) == Decimal("8")
    assert Decimal(str(comm["hours_pay"])) == Decimal("8") * Decimal("31.40")


def test_me_cash_and_notebook_self_entry_hit_own_revenue(portal_client: TestClient) -> None:
    c = portal_client
    ola = _emp(c, "Ola")
    code = _invite_code(c, ola)
    c.as_user("ola-sub", {"staff"})
    c.post("/invites/claim", json={"code": code})

    assert (
        c.post(
            "/me/cash",
            json={"entry_date": "2026-09-04", "service_name": "Manicure", "amount_pln": "120"},
        ).status_code
        == 201
    )
    assert (
        c.post(
            "/me/notebook",
            json={"entry_date": "2026-09-05", "service_name": "Pakiet twarz", "amount_pln": "200"},
        ).status_code
        == 201
    )

    rev = c.get("/me/revenue", params={"month": "2026-09"}).json()
    assert Decimal(str(rev["cash_services"])) == Decimal("120")
    assert Decimal(str(rev["notebook_services"])) == Decimal("200")
    assert Decimal(str(rev["services_total"])) == Decimal("320")


def test_unlinked_staff_blocked_from_scoped_endpoints(portal_client: TestClient) -> None:
    c = portal_client
    c.as_user("ghost", {"staff"})
    for path in ("/me/visits", "/me/revenue", "/me/commission", "/me/hours"):
        assert c.get(path, params={"month": "2026-09"}).status_code == 403
    assert c.post("/me/hours", json={"work_date": "2026-09-02", "hours": "8"}).status_code == 403
    assert (
        c.post(
            "/me/cash",
            json={"entry_date": "2026-09-02", "service_name": "X", "amount_pln": "10"},
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/me/notebook",
            json={"entry_date": "2026-09-02", "service_name": "X", "amount_pln": "10"},
        ).status_code
        == 403
    )


def test_non_staff_blocked_from_me(portal_client: TestClient) -> None:
    c = portal_client
    c.as_user("client-sub", {"client"})
    assert c.get("/me").status_code == 403  # require_role("staff") gate


def test_invites_admin_only(portal_client: TestClient) -> None:
    c = portal_client
    emp = _emp(c, "Ola")
    c.as_user("staff-sub", {"staff"})
    assert c.post("/invites", json={"employee_id": emp}).status_code == 403
    assert c.get("/invites").status_code == 403
