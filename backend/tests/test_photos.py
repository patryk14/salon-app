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
    monkeypatch.setattr(storage, "read_object", lambda key: f"BYTES:{key}".encode())
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
    assert "url" not in body  # no shareable link to a photo exists, by design

    # Gallery lists metadata; the bytes come only through the authenticated endpoint.
    photos = db_client.get(f"/clients/{cid}/photos").json()
    assert len(photos) == 1 and "url" not in photos[0]
    img = db_client.get(f"/photos/{photos[0]['id']}/content")
    assert img.status_code == 200 and img.content == f"BYTES:{key}".encode()
    assert img.headers["content-type"] == "image/jpeg"
    assert "no-store" in img.headers["cache-control"]


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
    assert photos[0]["uploaded_by"] is None  # staff audit hidden from the client
    mine = portal_client.get(f"/klient/me/photos/{photos[0]['id']}/content")
    assert mine.status_code == 200 and mine.content == b"BYTES:kMe"


def test_photo_bytes_are_row_scoped(portal_client: TestClient, fake_storage) -> None:
    """A photo is readable ONLY by staff/admin and by the client it belongs to."""
    c = portal_client
    mine, other = _client(c, "Ola", "Moja"), _client(c, "Ewa", "Cudza")
    ids = {}
    for cid, key in ((mine, "kMine"), (other, "kOther")):
        c.patch(f"/clients/{cid}", json={"photo_consent": True})
        ids[cid] = c.post(
            f"/clients/{cid}/photos", json={"s3_key": key, "content_type": "image/jpeg"}
        ).json()["id"]
    code = c.post("/invites", json={"client_id": mine}).json()["code"]

    c.as_user("client-sub-1", {"client"})
    assert c.post("/invites/claim", json={"code": code}).status_code == 200
    assert c.get(f"/klient/me/photos/{ids[mine]}/content").status_code == 200
    # someone else's photo id: a plain 404, same as a missing one (no probing)
    assert c.get(f"/klient/me/photos/{ids[other]}/content").status_code == 404
    assert c.get("/klient/me/photos/999999/content").status_code == 404
    # the staff endpoint is closed to clients entirely
    assert c.get(f"/photos/{ids[mine]}/content").status_code == 403

    # a logged-in but UNLINKED client gets nothing either
    c.as_user("stranger", {"client"})
    assert c.get(f"/klient/me/photos/{ids[mine]}/content").status_code == 403


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


# ------------------------------------------------------- duplicates (search/merge)
def test_search_matches_full_name_in_either_order(db_client: TestClient) -> None:
    _client(db_client, "Karolina", "Sobas")
    _client(db_client, "Karolina Sobas", "?")  # the Booksy-shaped duplicate
    for q in ("Karolina Sobas", "sobas karolina", "  Karolina   Sobas "):
        names = [c["last_name"] for c in db_client.get("/clients", params={"q": q}).json()["items"]]
        assert "Sobas" in names, q  # the real profile is found, not only the duplicate


def test_merge_moves_everything_and_fills_gaps(portal_client: TestClient, fake_storage) -> None:
    c = portal_client
    real = c.post(
        "/clients", json={"first_name": "Karolina", "last_name": "Sobas", "email": "k@x.pl"}
    ).json()["id"]
    dup = c.post(
        "/clients",
        json={
            "first_name": "Karolina Sobas",
            "last_name": "?",
            "email": "other@x.pl",
            "phone": "600100200",
        },
    ).json()["id"]
    c.patch(f"/clients/{dup}", json={"photo_consent": True})
    c.post(f"/clients/{dup}/photos", json={"s3_key": "kDup", "content_type": "image/jpeg"})
    c.post(
        f"/clients/{dup}/visits",
        json={"starts_at": "2026-09-10T10:00:00Z", "service_name": "Peeling"},
    )
    # the real profile owns the portal login
    code = c.post("/invites", json={"client_id": real}).json()["code"]
    c.as_user("client-sub-1", {"client"})
    assert c.post("/invites/claim", json={"code": code}).status_code == 200
    assert c.get("/klient/me/photos").json() == []  # the bug: photo sits on the duplicate

    c.as_user("test-admin", {"admin"})
    merged = c.post(f"/clients/{dup}/merge-into/{real}")
    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert body["email"] == "k@x.pl"  # the survivor's own data wins…
    assert body["phone"] == "600100200"  # …gaps are filled from the duplicate
    assert body["photo_consent"] is True
    assert c.get(f"/clients/{dup}").status_code == 404
    assert len(c.get(f"/clients/{real}/photos").json()) == 1
    assert c.get(f"/clients/{real}/visits").json()["total"] == 1
    assert fake_storage["deleted"] == []  # a merge never deletes photo objects

    c.as_user("client-sub-1", {"client"})
    assert len(c.get("/klient/me/photos").json()) == 1  # now she sees it


def test_merge_guards(portal_client: TestClient) -> None:
    c = portal_client
    a, b = _client(c, "Anna", "A"), _client(c, "Anna A", "?")
    assert c.post(f"/clients/{a}/merge-into/{a}").status_code == 400
    assert c.post(f"/clients/{a}/merge-into/999999").status_code == 404
    # two portal logins → refuse, a human must decide which one survives
    for cid, sub in ((a, "sub-a"), (b, "sub-b")):
        c.as_user("test-admin", {"admin"})
        code = c.post("/invites", json={"client_id": cid}).json()["code"]
        c.as_user(sub, {"client"})
        assert c.post("/invites/claim", json={"code": code}).status_code == 200
    c.as_user("test-admin", {"admin"})
    assert c.post(f"/clients/{b}/merge-into/{a}").status_code == 409
    c.as_user("staff-x", {"staff"})
    assert c.post(f"/clients/{b}/merge-into/{a}").status_code == 403


def test_pull_customers_splits_full_name_and_matches_existing(monkeypatch) -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app import booksy_api
    from app.models import Base, Client

    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    db.add(Client(first_name="Karolina", last_name="Sobas"))
    db.flush()

    page = {
        "customers": [
            {"merged_data": {"id": 46672185, "first_name": "Karolina Sobas", "last_name": ""}}
        ]
    }
    monkeypatch.setattr(
        booksy_api, "load_credentials", lambda db: booksy_api.BooksyCredentials("1", "t", "k", "f")
    )
    monkeypatch.setattr(
        booksy_api,
        "_get_json",
        lambda creds, url, timeout=60: page if url.endswith("page=1") else {"customers": []},
    )

    res = booksy_api.pull_customers(db, per_page=100)
    assert (res["created"], res["updated"]) == (0, 1)  # matched, no duplicate
    rows = db.scalars(select(Client)).all()
    assert len(rows) == 1 and rows[0].booksy_customer_id == 46672185


def test_merge_keeps_the_better_name(db_client: TestClient, fake_storage) -> None:
    """Merging the proper profile INTO the Booksy-shaped one must not leave the
    survivor called "Karolina Sobas ?"."""
    real = _client(db_client, "Karolina", "Sobas")
    dup = _client(db_client, "Karolina Sobas", "?")
    body = db_client.post(f"/clients/{real}/merge-into/{dup}").json()
    assert (body["first_name"], body["last_name"]) == ("Karolina", "Sobas")

    # …and a proper target name is never overwritten by the duplicate's
    a = _client(db_client, "Anna", "Nowak")
    b = _client(db_client, "Ania", "Nowak-Kowalska")
    body = db_client.post(f"/clients/{b}/merge-into/{a}").json()
    assert (body["first_name"], body["last_name"]) == ("Anna", "Nowak")
