"""Service catalog + rebooking (F8): sync from visits, set an interval, and get
the due-list (admin) + the client's 'suggested next visit'."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def _session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models import Base

    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_catalog_admin_only(portal_client: TestClient) -> None:
    portal_client.as_user("staff-x", {"staff"})
    assert portal_client.get("/catalog").status_code == 403


def test_catalog_sync_set_interval_and_due(db_client: TestClient) -> None:
    cid = db_client.post("/clients", json={"first_name": "Ola", "last_name": "Rebook"}).json()["id"]
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    r = db_client.post(
        f"/clients/{cid}/visits",
        json={"starts_at": old, "service_name": "Endermologia", "status": "completed"},
    )
    assert r.status_code == 201, r.text

    s = db_client.post("/catalog/sync").json()
    assert s["created"] >= 1
    svc = next(x for x in db_client.get("/catalog").json() if x["name"] == "Endermologia")
    assert svc["visit_count"] == 1 and svc["rebook_interval_days"] is None

    db_client.patch(f"/catalog/{svc['id']}", json={"rebook_interval_days": 30})
    # last visit 40 days ago + 30 → due 10 days ago → within the 14-day horizon
    due = db_client.get("/catalog/due?within_days=14").json()
    assert any(d["client_id"] == cid and d["service"] == "Endermologia" for d in due)

    # re-sync is idempotent
    assert db_client.post("/catalog/sync").json()["created"] == 0


def test_client_rebooking_suggestion() -> None:
    from app.models import Client, Service, Visit
    from app.routers.client_portal import my_rebooking

    db = _session()
    c = Client(first_name="Ala", last_name="K")
    db.add(c)
    db.flush()
    db.add(
        Visit(
            client_id=c.id,
            starts_at=datetime.now(UTC) - timedelta(days=50),
            service_name="Masaż Kobido",
            status="completed",
        )
    )
    db.add(Service(name="Masaż Kobido", rebook_interval_days=30, recommendation="co miesiąc"))
    # a service with no interval is not suggested
    db.add(Service(name="Nieustawiona", rebook_interval_days=None))
    db.flush()

    out = my_rebooking(c, db)
    assert len(out) == 1
    assert out[0].service == "Masaż Kobido"
    assert out[0].due is True  # 50 days ago + 30 < today
    assert out[0].recommendation == "co miesiąc"
    db.close()
