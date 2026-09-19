"""Progress photos (F9): consent-gated two-step upload, the client's own gallery,
per-photo delete and RODO erasure (S3 purge + tombstone that blocks re-import).

Object storage is stubbed — presigning/deletion are exercised against MinIO/S3
in compose, not here; these tests own the API logic (consent gate, audit, visit
ownership, erasure) on in-memory SQLite."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fake_storage(monkeypatch):
    """Replace the S3 layer with an in-memory spy — no MinIO needed."""
    from app import storage

    seq = {"n": 0}
    calls = {"deleted": []}

    def _new_key(client_id: int, content_type: str) -> str:
        seq["n"] += 1
        return f"clients/{client_id}/photos/{seq['n']}.jpg"

    monkeypatch.setattr(storage, "new_key", _new_key)
    monkeypatch.setattr(storage, "presign_put", lambda key, ct: f"https://put/{key}")
    monkeypatch.setattr(storage, "presign_get", lambda key: f"https://get/{key}")
    monkeypatch.setattr(storage, "delete_objects", lambda keys: calls["deleted"].extend(keys))
    return calls


def _client(c: TestClient, first="Ola", last="Test") -> int:
    r = c.post("/clients", json={"first_name": first, "last_name": last})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_upload_and_register_gated_by_consent(db_client: TestClient, fake_storage) -> None:
    cid = _client(db_client)

    # No consent → neither the presigned URL nor registration is allowed.
    jpeg = {"content_type": "image/jpeg"}
    assert db_client.post(f"/clients/{cid}/photos/upload-url", json=jpeg).status_code == 409
    assert db_client.post(f"/clients/{cid}/photos", json={"s3_key": "k", **jpeg}).status_code == 409

    # Grant consent — the timestamp is stamped.
    patched = db_client.patch(f"/clients/{cid}", json={"photo_consent": True}).json()
    assert patched["photo_consent"] is True
    assert patched["photo_consent_at"] is not None

    # Step 1: presigned PUT URL.
    up = db_client.post(f"/clients/{cid}/photos/upload-url", json={"content_type": "image/jpeg"})
    assert up.status_code == 200, up.text
    key = up.json()["s3_key"]
    assert up.json()["upload_url"].startswith("https://put/")

    # Step 2: register the object, tagged to a visit + before/after.
    v = db_client.post(
        f"/clients/{cid}/visits",
        json={"starts_at": "2026-09-10T10:00:00Z", "service_name": "Peeling"},
    ).json()
    reg = db_client.post(
        f"/clients/{cid}/photos",
        json={
            "s3_key": key,
            "content_type": "image/jpeg",
            "visit_id": v["id"],
            "kind": "before",
            "note": "start",
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    assert body["kind"] == "before" and body["visit_id"] == v["id"]
    assert body["uploaded_by"] == "test-admin"  # audit: who
    assert body["taken_on"] is not None  # defaults to upload day
    assert body["url"].startswith("https://get/")

    # Gallery lists it with a fresh view URL.
    photos = db_client.get(f"/clients/{cid}/photos").json()
    assert len(photos) == 1 and photos[0]["url"].startswith("https://get/")


def test_register_rejects_foreign_visit(db_client: TestClient, fake_storage) -> None:
    a = _client(db_client, "Anna", "A")
    b = _client(db_client, "Beata", "B")
    db_client.patch(f"/clients/{a}", json={"photo_consent": True})
    vb = db_client.post(
        f"/clients/{b}/visits",
        json={"starts_at": "2026-09-10T10:00:00Z", "service_name": "X"},
    ).json()
    r = db_client.post(
        f"/clients/{a}/photos",
        json={"s3_key": "k1", "content_type": "image/jpeg", "visit_id": vb["id"]},
    )
    assert r.status_code == 400, r.text


def test_delete_photo_purges_object(db_client: TestClient, fake_storage) -> None:
    cid = _client(db_client)
    db_client.patch(f"/clients/{cid}", json={"photo_consent": True})
    pid = db_client.post(
        f"/clients/{cid}/photos", json={"s3_key": "kX", "content_type": "image/jpeg"}
    ).json()["id"]

    assert db_client.delete(f"/photos/{pid}").status_code == 204
    assert "kX" in fake_storage["deleted"]
    assert db_client.get(f"/clients/{cid}/photos").json() == []


def test_ordinary_delete_client_purges_storage(db_client: TestClient, fake_storage) -> None:
    cid = _client(db_client)
    db_client.patch(f"/clients/{cid}", json={"photo_consent": True})
    db_client.post(f"/clients/{cid}/photos", json={"s3_key": "kDel", "content_type": "image/jpeg"})

    assert db_client.delete(f"/clients/{cid}").status_code == 204
    assert "kDel" in fake_storage["deleted"]
    assert db_client.get(f"/clients/{cid}").status_code == 404


def test_rodo_erase_purges_and_deletes(db_client: TestClient, fake_storage) -> None:
    cid = _client(db_client)
    db_client.patch(f"/clients/{cid}", json={"photo_consent": True})
    db_client.post(
        f"/clients/{cid}/photos", json={"s3_key": "kErase", "content_type": "image/jpeg"}
    )

    res = db_client.post(f"/clients/{cid}/erase")
    assert res.status_code == 200, res.text
    assert res.json() == {"erased": True, "tombstoned": False}  # no Booksy id → no tombstone
    assert "kErase" in fake_storage["deleted"]
    assert db_client.get(f"/clients/{cid}").status_code == 404


def test_erase_requires_admin(portal_client: TestClient) -> None:
    cid = _client(portal_client)
    portal_client.as_user("staff-x", {"staff"})
    assert portal_client.post(f"/clients/{cid}/erase").status_code == 403


def test_client_sees_own_photos(portal_client: TestClient, fake_storage) -> None:
    # Admin: client + consent + a photo, then issue an invite.
    cid = _client(portal_client)
    portal_client.patch(f"/clients/{cid}", json={"photo_consent": True})
    portal_client.post(
        f"/clients/{cid}/photos", json={"s3_key": "kMe", "content_type": "image/jpeg"}
    )
    code = portal_client.post("/invites", json={"client_id": cid}).json()["code"]

    # The client claims the invite and sees her gallery (no uploader identity).
    portal_client.as_user("client-sub-1", {"client"})
    assert portal_client.post("/invites/claim", json={"code": code}).status_code == 200
    photos = portal_client.get("/klient/me/photos").json()
    assert len(photos) == 1
    assert photos[0]["url"].startswith("https://get/")
    assert photos[0]["uploaded_by"] is None  # staff audit hidden from the client


def test_pull_customers_skips_tombstoned(monkeypatch) -> None:
    """A RODO-erased Booksy id must never be recreated by a later backfill."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app import booksy_api
    from app.models import Base, Client, ClientTombstone

    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(ClientTombstone(booksy_customer_id=222))
    db.flush()

    pages = {
        1: {
            "customers": [
                {"merged_data": {"id": 111, "first_name": "Anna", "last_name": "Nowak"}},
                {"merged_data": {"id": 222, "first_name": "Erased", "last_name": "Client"}},
            ]
        }
    }
    monkeypatch.setattr(
        booksy_api, "load_credentials", lambda db: booksy_api.BooksyCredentials("1", "t", "k", "f")
    )
    monkeypatch.setattr(
        booksy_api,
        "_get_json",
        lambda creds, url, timeout=60: pages.get(int(url.split("page=")[-1]), {"customers": []}),
    )

    res = booksy_api.pull_customers(db, per_page=100)
    assert res["created"] == 1  # only Anna; the tombstoned id is skipped
    names = {c.booksy_customer_id for c in db.scalars(select(Client)).all()}
    assert names == {111}
