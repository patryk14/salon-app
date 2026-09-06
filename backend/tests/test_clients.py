"""CRUD tests for clients and visits (in-memory SQLite via db_client fixture)."""

from fastapi.testclient import TestClient


def _create_client(db_client: TestClient, **overrides) -> dict:
    payload = {"first_name": "Anna", "last_name": "Kowalska", "phone": "+48500100200"}
    payload.update(overrides)
    resp = db_client.post("/clients", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_get_client(db_client: TestClient) -> None:
    created = _create_client(db_client, email="anna@example.com")
    got = db_client.get(f"/clients/{created['id']}")
    assert got.status_code == 200
    body = got.json()
    assert body["first_name"] == "Anna"
    assert body["email"] == "anna@example.com"
    assert body["created_at"]  # timestamps come from server_default


def test_list_clients_search_and_paging(db_client: TestClient) -> None:
    _create_client(db_client)
    _create_client(db_client, first_name="Beata", last_name="Nowak", phone="+48600200300")

    everyone = db_client.get("/clients").json()
    assert everyone["total"] == 2

    hit = db_client.get("/clients", params={"q": "nowak"}).json()
    assert hit["total"] == 1
    assert hit["items"][0]["first_name"] == "Beata"

    by_phone = db_client.get("/clients", params={"q": "500100"}).json()
    assert by_phone["items"][0]["last_name"] == "Kowalska"

    page = db_client.get("/clients", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1


def test_patch_client_partial(db_client: TestClient) -> None:
    created = _create_client(db_client)
    resp = db_client.patch(f"/clients/{created['id']}", json={"notes": "skóra wrażliwa"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] == "skóra wrażliwa"
    assert body["first_name"] == "Anna"  # untouched fields survive PATCH


def test_client_404(db_client: TestClient) -> None:
    assert db_client.get("/clients/4242").status_code == 404
    assert db_client.patch("/clients/4242", json={"notes": "x"}).status_code == 404
    assert db_client.delete("/clients/4242").status_code == 404


def test_visit_lifecycle(db_client: TestClient) -> None:
    client_id = _create_client(db_client)["id"]

    resp = db_client.post(
        f"/clients/{client_id}/visits",
        json={
            "starts_at": "2026-09-10T14:00:00+02:00",
            "service_name": "Peeling chemiczny",
            "price_pln": "250.00",
        },
    )
    assert resp.status_code == 201, resp.text
    visit = resp.json()
    assert visit["status"] == "scheduled"

    resp = db_client.patch(f"/visits/{visit['id']}", json={"status": "completed"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    listed = db_client.get(f"/clients/{client_id}/visits").json()
    assert listed["total"] == 1

    assert db_client.patch("/visits/999", json={"status": "completed"}).status_code == 404


def test_visit_rejects_unknown_status(db_client: TestClient) -> None:
    client_id = _create_client(db_client)["id"]
    resp = db_client.post(
        f"/clients/{client_id}/visits",
        json={"starts_at": "2026-09-10T14:00:00+02:00", "service_name": "X", "status": "typo"},
    )
    assert resp.status_code == 422


def test_delete_client_cascades_visits(db_client: TestClient) -> None:
    client_id = _create_client(db_client)["id"]
    db_client.post(
        f"/clients/{client_id}/visits",
        json={"starts_at": "2026-09-10T14:00:00+02:00", "service_name": "Regulacja brwi"},
    )
    assert db_client.delete(f"/clients/{client_id}").status_code == 204
    assert db_client.get(f"/clients/{client_id}").status_code == 404
