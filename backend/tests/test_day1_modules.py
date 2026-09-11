"""Day 1 modules: supply list, staff documents, availability + time off.

Uses portal_client (swappable identity over one DB): act as admin, then as a
linked staff sub. Reuses the invite/claim helpers from the staff-portal suite.
"""

from fastapi.testclient import TestClient

from tests.test_staff_portal import _emp, _invite_code


def _link_staff(c: TestClient, name: str = "Ola", sub: str = "ola-sub") -> int:
    """Create an employee, claim an invite as `sub` → returns employee id."""
    emp = _emp(c, name)
    code = _invite_code(c, emp)
    c.as_user(sub, {"staff"})
    c.post("/invites/claim", json={"code": code})
    return emp


# ------------------------------------------------------------------ supplies
def test_supplies_add_mark_bought_delete(portal_client: TestClient) -> None:
    c = portal_client  # starts as admin
    r = c.post("/supplies", json={"name": "  Wata kosmetyczna  "})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["name"] == "Wata kosmetyczna"  # trimmed
    assert item["status"] == "to_buy" and item["created_by"] == "test-admin"

    # mark bought → stamps bought_at
    upd = c.patch(f"/supplies/{item['id']}", json={"status": "bought"}).json()
    assert upd["status"] == "bought" and upd["bought_at"] is not None
    # un-buy clears the stamp
    upd = c.patch(f"/supplies/{item['id']}", json={"status": "to_buy"}).json()
    assert upd["bought_at"] is None

    assert len(c.get("/supplies").json()) == 1
    assert c.delete(f"/supplies/{item['id']}").status_code == 204
    assert c.get("/supplies").json() == []


def test_supplies_staff_can_add(portal_client: TestClient) -> None:
    c = portal_client
    c.as_user("staff-sub", {"staff"})  # no employee link needed — shared list
    assert c.post("/supplies", json={"name": "Rękawiczki"}).status_code == 201
    assert c.get("/supplies").json()[0]["created_by"] == "staff-sub"


# ------------------------------------------------------------ staff documents
def test_staff_documents_admin_creates_staff_reads_own(portal_client: TestClient) -> None:
    c = portal_client
    emp = _emp(c, "Ola")
    r = c.post(
        "/staff-documents",
        json={"employee_id": emp, "doc_type": "umowa", "valid_until": "2026-12-31"},
    )
    assert r.status_code == 201, r.text
    assert len(c.get("/staff-documents", params={"employee_id": emp}).json()) == 1

    # link the employee and read her own docs
    code = _invite_code(c, emp)
    c.as_user("ola-sub", {"staff"})
    c.post("/invites/claim", json={"code": code})
    mine = c.get("/me/documents").json()
    assert len(mine) == 1 and mine[0]["valid_until"] == "2026-12-31"

    # staff cannot create documents (admin-only)
    assert c.post("/staff-documents", json={"employee_id": emp}).status_code == 403


# --------------------------------------------------------- availability + off
def test_availability_upsert_and_admin_view(portal_client: TestClient) -> None:
    c = portal_client
    emp = _link_staff(c)
    assert (
        c.post(
            "/me/availability",
            json={"work_date": "2026-09-15", "from_time": "09:00", "to_time": "17:00"},
        ).status_code
        == 201
    )
    # re-post same day overwrites (one row per day)
    c.post("/me/availability", json={"work_date": "2026-09-15", "from_time": "10:00"})
    mine = c.get("/me/availability", params={"month": "2026-09"}).json()
    assert len(mine) == 1 and mine[0]["from_time"] == "10:00:00"

    # admin sees it salon-wide
    c.as_user("test-admin", {"admin"})
    allrows = c.get("/scheduling/availability", params={"month": "2026-09"}).json()
    assert any(a["employee_id"] == emp and a["work_date"] == "2026-09-15" for a in allrows)


def test_time_off_request_validate_and_approve(portal_client: TestClient) -> None:
    c = portal_client
    _link_staff(c)
    # bad range rejected
    assert (
        c.post(
            "/me/time-off", json={"start_date": "2026-09-20", "end_date": "2026-09-18"}
        ).status_code
        == 400
    )
    off = c.post("/me/time-off", json={"start_date": "2026-09-20", "end_date": "2026-09-25"}).json()
    assert off["status"] == "requested"

    # admin approves
    c.as_user("test-admin", {"admin"})
    approved = c.patch(f"/scheduling/time-off/{off['id']}", json={"status": "approved"}).json()
    assert approved["status"] == "approved"
    assert len(c.get("/scheduling/time-off", params={"status": "approved"}).json()) == 1

    # staff sees the approved state on her own row
    c.as_user("ola-sub", {"staff"})
    assert c.get("/me/time-off").json()[0]["status"] == "approved"


def test_scheduling_self_service_needs_link(portal_client: TestClient) -> None:
    c = portal_client
    c.as_user("ghost", {"staff"})  # authenticated staff, but not linked
    assert c.get("/me/documents").status_code == 403
    assert c.get("/me/availability", params={"month": "2026-09"}).status_code == 403
    assert c.post("/me/availability", json={"work_date": "2026-09-15"}).status_code == 403
    assert c.get("/me/time-off").status_code == 403
