"""packages_summary parser: pull client packages (value, count, remaining,
expiry); the count comes from the 'X / Y' denominator, not the name."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.packages import parse_packages_summary

_HDR = [
    "",
    "",
    "Nabywca",
    "Imię i nazwisko",
    "Nazwa",
    "Numer pakietu",
    "Cena",
    "Aktualna wartość",
    "Ważność od",
    "Ważność do",
    "Dni",
]


def _row(idx, client, name, number, price, value, vfrom, vuntil):
    return ["", idx, " ", client, name, number, price, value, vfrom, vuntil, "1"]


def test_parse_packages_summary() -> None:
    grid = [
        ["", "Bliski termin wygaśnięcia"],
        _HDR,
        _row(
            "1",
            "Magdalena Wiekierak",
            "Endermologia 15x",
            "9700005494231",
            "2000",
            "5 / 15",
            "18.06.2026",
            "16.09.2026",
        ),
        ["", "Aktywny"],
        _HDR,
        _row(
            "2",
            "Patrycja Gazda",
            "Depilacja laserowa",
            "9700005935529",
            "1700",
            "8 / 10",
            "13.08.2026",
            "11.11.2026",
        ),
        _row(
            "3",
            "Ewa Wypasek",
            "Endermologia 15x",
            "9700002550145",
            "2000",
            "0 / 15",
            "15.04.2025",
            "14.07.2025",
        ),
    ]
    pkgs = parse_packages_summary(grid)
    assert len(pkgs) == 3  # header/section rows skipped

    p = pkgs[0]
    assert p.booksy_number == "9700005494231"
    assert p.client_name == "Magdalena Wiekierak"
    assert p.total_value == Decimal("2000")
    assert p.total_treatments == 15  # denominator of "5 / 15", NOT the "15x" in the name
    assert p.remaining == 5
    assert p.valid_until == date(2026, 9, 16)

    # count comes from X/Y, so a name without "Nx" still parses:
    assert pkgs[1].total_treatments == 10 and pkgs[1].remaining == 8
    assert pkgs[2].remaining == 0  # expired package kept (0 / 15)


def test_packages_endpoint_admin_only(portal_client: TestClient) -> None:
    portal_client.as_user("staff-sub", {"staff"})
    assert portal_client.get("/packages").status_code == 403


def test_package_redemption_feeds_notebook_services() -> None:
    """A package redemption credits the performer's prepaid-services base
    (notebook_services), summed with the legacy manual notebook."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.derivation import monthly_notebook_services
    from app.models import Base, Employee, NotebookEntry, PackageRedemption

    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    e = Employee(display_name="Ola")
    db.add(e)
    db.flush()
    db.add(
        NotebookEntry(
            employee_id=e.id,
            entry_date=date(2026, 9, 5),
            service_name="X",
            amount_pln=Decimal("100"),
        )
    )
    db.add(
        PackageRedemption(
            booksy_ref="D1",
            employee_id=e.id,
            client_name="K",
            redemption_date=date(2026, 9, 10),
            value=Decimal("133"),
        )
    )
    db.add(
        PackageRedemption(
            booksy_ref="D2",
            employee_id=e.id,
            client_name="K",
            redemption_date=date(2026, 10, 1),
            value=Decimal("50"),
        )
    )
    db.flush()
    assert monthly_notebook_services(db, e.id, "2026-09") == Decimal(
        "233"
    )  # 100 manual + 133 package
    db.close()
