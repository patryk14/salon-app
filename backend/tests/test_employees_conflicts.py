"""Employee names and aliases are unique — a duplicate is a readable 409, not a
500 from the database (found on Postgres, where the roster is pre-seeded)."""

from fastapi.testclient import TestClient


def test_duplicate_employee_name_or_alias_is_a_409(db_client: TestClient) -> None:
    c = db_client
    first = c.post(
        "/employees", json={"display_name": "Julia", "aliases": ["Julia K.", "Julia K."]}
    )
    assert first.status_code == 201, first.text
    assert [a["alias"] for a in first.json()["aliases"]] == ["Julia K."]  # de-duplicated

    dup = c.post("/employees", json={"display_name": "Julia"})
    assert dup.status_code == 409 and "Julia" in dup.json()["detail"]
    alias_dup = c.post("/employees", json={"display_name": "Ola", "aliases": ["Julia K."]})
    assert alias_dup.status_code == 409

    ola = c.post("/employees", json={"display_name": "Ola"}).json()["id"]
    assert c.patch(f"/employees/{ola}", json={"display_name": "Julia"}).status_code == 409
    # renaming to her own name, or changing something else, is fine
    assert c.patch(f"/employees/{ola}", json={"display_name": "Ola"}).status_code == 200
    assert c.patch(f"/employees/{ola}", json={"fte_factor": "0.5"}).status_code == 200
