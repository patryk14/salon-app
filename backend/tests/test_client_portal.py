"""Client portal (F7): admin issues a client invite, the client claims it (same
atomic flow as staff), and then sees only her OWN visits, packages and vouchers.
Client.notes is never exposed here."""

from datetime import UTC, datetime
from decimal import Decimal

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


def test_client_invite_claim_and_whoami(portal_client: TestClient) -> None:
    c = portal_client.post("/clients", json={"first_name": "Ola", "last_name": "Test"})
    assert c.status_code in (200, 201), c.text
    cid = c.json()["id"]

    inv = portal_client.post("/invites", json={"client_id": cid})
    assert inv.status_code == 201, inv.text
    assert inv.json()["role"] == "client" and inv.json()["client_id"] == cid
    code = inv.json()["code"]

    portal_client.as_user("client-sub-1", {"client"})
    claimed = portal_client.post("/invites/claim", json={"code": code})
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["role"] == "client"

    me = portal_client.get("/klient/me").json()
    assert me["linked"] is True
    assert me["client_id"] == cid and me["first_name"] == "Ola"


def test_client_portal_rejects_staff(portal_client: TestClient) -> None:
    portal_client.as_user("staff-x", {"staff"})
    assert portal_client.get("/klient/me").status_code == 403


def test_unlinked_client_gets_claim_box_but_no_data(portal_client: TestClient) -> None:
    portal_client.as_user("fresh-client", {"client"})
    assert portal_client.get("/klient/me").json()["linked"] is False  # drives the claim box
    # data endpoints require a link (row scope) — 403 until claimed
    assert portal_client.get("/klient/me/visits?month=2026-09").status_code == 403


def test_client_portal_is_row_scoped() -> None:
    from app.models import Client, Package, Visit, Voucher
    from app.routers.client_portal import my_packages, my_visits, my_vouchers

    db = _session()
    a = Client(first_name="Anna", last_name="Nowak")
    b = Client(first_name="Beata", last_name="Kowalska")
    db.add_all([a, b])
    db.flush()
    db.add_all(
        [
            Visit(
                client_id=a.id,
                starts_at=datetime(2026, 9, 10, 10, tzinfo=UTC),
                service_name="Masaż Kobido",
                status="completed",
            ),
            Visit(
                client_id=b.id,
                starts_at=datetime(2026, 9, 10, 11, tzinfo=UTC),
                service_name="Pedicure",
                status="completed",
            ),
            Package(
                booksy_number="PA",
                client_id=a.id,
                client_name="Anna Nowak",
                name="Endermologia 10x",
                total_value=Decimal("1500"),
                total_treatments=10,
                remaining=6,
            ),
            Package(
                booksy_number="PB",
                client_id=b.id,
                client_name="Beata Kowalska",
                name="Bikini 6x",
                total_value=Decimal("900"),
                total_treatments=6,
                remaining=6,
            ),
            Voucher(
                client_name="p.Anna Nowak",  # prefix — matched by substring
                description="300 zł",
                total_value=Decimal("300"),
                remaining_value=Decimal("300"),
            ),
        ]
    )
    db.flush()

    assert [v.service_name for v in my_visits(a, db, "2026-09")] == ["Masaż Kobido"]
    pkgs = my_packages(a, db)
    assert [p.name for p in pkgs] == ["Endermologia 10x"] and pkgs[0].remaining == 6
    vch = my_vouchers(a, db)
    assert len(vch) == 1 and vch[0].description == "300 zł"
    # B sees only her own — not Anna's voucher/visits/packages
    assert my_vouchers(b, db) == []
    assert [v.service_name for v in my_visits(b, db, "2026-09")] == ["Pedicure"]
    assert [p.name for p in my_packages(b, db)] == ["Bikini 6x"]
    db.close()
