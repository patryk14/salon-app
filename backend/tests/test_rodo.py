"""RODO erasure that survives a re-import: the client is gone, her visits stay as
anonymous business records (the performer keeps her commission), her name is
scrubbed everywhere it lived as text, and re-syncing old dates from Booksy cannot
bring her back — while a later namesake is still a normal new client."""

import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.rodo import ANON_NAME, ErasedNames, _digest, name_key

PAST = "2026-08-12"  # any day before "today": her history
ANON = {"first_name": "Klientka usunięta", "last_name": "(RODO)"}


def _db(c: TestClient):
    from app.deps import get_db

    return next(c.app.dependency_overrides[get_db]())


def _visit_rows(*rows):
    from app.booksy import VisitRow

    return [
        VisitRow(
            booksy_ref=ref,
            client_name=name,
            starts_at=datetime.fromisoformat(f"{day}T10:00:00").replace(tzinfo=UTC),
            service_name="Peeling",
            status="completed",
            price_pln=Decimal(price),
            staff_name="Julia",
        )
        for ref, name, day, price in rows
    ]


def _import(c: TestClient, *rows) -> None:
    from app.routers.imports import import_visit_rows

    db = _db(c)
    import_visit_rows(db, _visit_rows(*rows))
    db.commit()


def _client_id(c: TestClient, q: str) -> int | None:
    items = c.get("/clients", params={"q": q}).json()["items"]
    return items[0]["id"] if items else None


def test_name_key_is_order_and_noise_independent() -> None:
    assert (
        name_key("Anna", "Kowalska") == name_key("KOWALSKA  anna") == name_key("Anna Kowalska", "?")
    )
    assert name_key("Anna", "Kowalska") != name_key("Anna", "Kowalska-Nowak")  # hyphen = one token
    assert name_key("", "?") == ""


def test_suppression_is_a_salted_hash_and_time_bound() -> None:
    key = name_key("Anna Kowalska")
    erased = ErasedNames((("s1", _digest("s1", key), 2, date(2026, 9, 1)),))
    assert erased.matches("Kowalska Anna", date(2026, 8, 12))  # her history
    assert erased.matches("anna kowalska", date(2026, 9, 1))  # the erasure day itself
    assert not erased.matches("Anna Kowalska", date(2026, 9, 2))  # a later namesake
    assert erased.matches("Anna Kowalska", None)  # undated → err on the side of privacy
    assert not erased.matches("Anna Kowalska-Nowak", date(2026, 8, 12))
    assert not erased.matches("", None)
    # hand-typed cells: the name plus a word or two — same rule for scrub and import
    assert erased.mentions("Anna Kowalska — prezent", date(2026, 8, 1))
    assert erased.mentions("prezent dla: Kowalska Anna", None)
    assert not erased.mentions("Anna Kowalska-Nowak (prezent)", None)
    assert not erased.mentions("Anna Nowak, Ewa Kowalska", None)  # two OTHER people
    one = ErasedNames((("s2", _digest("s2", "anna"), 1, date(2026, 9, 1)),))
    assert one.mentions("Anna", None) and not one.mentions("Anna Kowalska", None)


def test_erase_keeps_the_commission_and_leaves_no_name(db_client: TestClient) -> None:
    c = db_client
    julia = c.post("/employees", json={"display_name": "Julia", "aliases": ["Julia"]}).json()["id"]
    _import(c, ("B-1", "Anna Kowalska", PAST, "400"), ("B-2", "Inna Osoba", PAST, "100"))
    anna = _client_id(c, "Anna Kowalska")
    v = c.get(f"/clients/{anna}/visits").json()["items"][0]
    c.patch(f"/visits/{v['id']}", json={"notes": "uczulenie na kwasy"})  # personal → must go

    c.post("/settlement/periods", json={"year_month": PAST[:7]})
    before = c.post(f"/settlement/periods/{PAST[:7]}/lines/{julia}/derive").json()
    assert Decimal(before["booksy_services"]) == Decimal("500")

    res = c.post(f"/clients/{anna}/erase").json()
    assert res["erased"] is True and res["visits_anonymised"] == 1
    assert c.get(f"/clients/{anna}").status_code == 404
    assert _client_id(c, "Kowalska") is None and _client_id(c, "usunięta") is None  # hidden

    after = c.post(f"/settlement/periods/{PAST[:7]}/lines/{julia}/derive").json()
    assert Decimal(after["booksy_services"]) == Decimal("500")  # Julia lost nothing

    from sqlalchemy import select

    from app.models import Client, ErasedName, Visit

    db = _db(c)
    anon = db.scalar(select(Client).where(Client.is_anonymous.is_(True)))
    kept = db.scalar(select(Visit).where(Visit.booksy_ref == "B-1"))
    assert kept.client_id == anon.id and kept.notes is None and kept.price_pln == Decimal("400")
    entry = db.scalar(select(ErasedName))
    assert "kowalska" not in (entry.name_hash + entry.salt).lower() and len(entry.name_hash) == 64


def test_reimport_cannot_bring_her_back_but_a_namesake_is_a_new_client(
    db_client: TestClient,
) -> None:
    c = db_client
    _import(c, ("B-1", "Anna Kowalska", PAST, "400"))
    c.post(f"/clients/{_client_id(c, 'Anna Kowalska')}/erase")

    # the owner re-pulls August from Booksy: same visit (updated price) + an older one
    _import(c, ("B-1", "Anna Kowalska", PAST, "450"), ("B-0", "Kowalska Anna", "2026-07-01", "90"))
    assert _client_id(c, "Kowalska") is None  # not recreated — in either name order

    from sqlalchemy import select

    from app.models import Client, Visit

    db = _db(c)
    anon_id = db.scalar(select(Client.id).where(Client.is_anonymous.is_(True)))
    rows = db.execute(select(Visit.booksy_ref, Visit.client_id, Visit.price_pln)).all()
    assert sorted(rows) == [("B-0", anon_id, Decimal("90")), ("B-1", anon_id, Decimal("450"))]

    # a DIFFERENT Anna Kowalska books after the erasure → an ordinary new client
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    _import(c, ("B-9", "Anna Kowalska", tomorrow, "200"))
    new_id = _client_id(c, "Anna Kowalska")
    assert new_id is not None and new_id != anon_id
    assert c.get(f"/clients/{new_id}/visits").json()["total"] == 1


def test_erase_scrubs_every_text_copy_of_her_name(db_client: TestClient) -> None:
    from sqlalchemy import select

    from app.models import Package, PackageRedemption, RegisterTxn, Voucher

    c = db_client
    cid = c.post("/clients", json={"first_name": "Anna", "last_name": "Kowalska"}).json()["id"]
    db = _db(c)
    day = date.fromisoformat(PAST)
    db.add_all(
        [
            RegisterTxn(day=day, client_name="Anna Kowalska", inflow=Decimal("350")),
            RegisterTxn(day=day, client_name="Anna Kowalska-Nowak", inflow=Decimal("10")),
            Package(booksy_number="P1", client_id=cid, client_name="Kowalska Anna", name="Endermo",
                    total_value=Decimal("900"), total_treatments=10, remaining=4),
            PackageRedemption(booksy_ref="R1", client_name="Anna Kowalska", redemption_date=day),
            Voucher(client_name="Anna Kowalska — prezent", description="300 zł",
                    total_value=Decimal("300"), remaining_value=Decimal("300")),
            Voucher(client_name="Anna Kowalska-Nowak", description="100 zł",
                    total_value=Decimal("100"), remaining_value=Decimal("100")),
        ]
    )  # fmt: skip
    db.commit()

    assert c.post(f"/clients/{cid}/erase").status_code == 200
    db = _db(c)
    assert sorted(str(n) for n in db.scalars(select(RegisterTxn.client_name))) == [
        "Anna Kowalska-Nowak", "None"]  # fmt: skip
    pkg = db.scalar(select(Package))
    assert pkg.client_name == ANON_NAME and pkg.remaining == 4  # the money stays, the name goes
    assert db.scalar(select(PackageRedemption.client_name)) == ANON_NAME
    assert sorted(db.scalars(select(Voucher.client_name))) == ["Anna Kowalska-Nowak", ANON_NAME]


def test_the_placeholder_cannot_be_touched(portal_client: TestClient) -> None:
    c = portal_client
    _import(c, ("B-1", "Anna Kowalska", PAST, "400"))
    c.post(f"/clients/{_client_id(c, 'Anna Kowalska')}/erase")
    from sqlalchemy import select

    from app.models import Client

    anon = _db(c).scalar(select(Client.id).where(Client.is_anonymous.is_(True)))
    other = c.post("/clients", json={"first_name": "Ewa", "last_name": "Nowak"}).json()["id"]

    assert c.get(f"/clients/{anon}").json()["first_name"] == ANON["first_name"]  # readable by id
    assert c.patch(f"/clients/{anon}", json={"first_name": "X"}).status_code == 409
    assert c.delete(f"/clients/{anon}").status_code == 409
    assert c.post(f"/clients/{anon}/erase").status_code == 409  # would delete everyone's visits
    assert c.post(f"/clients/{anon}/merge-into/{other}").status_code == 409
    assert c.post(f"/clients/{other}/merge-into/{anon}").status_code == 409
    # a login on it would see every erased client's visits
    assert c.post("/invites", json={"client_id": anon}).status_code == 409


def test_a_second_erasure_reuses_the_same_placeholder(db_client: TestClient) -> None:
    c = db_client
    _import(c, ("B-1", "Anna Kowalska", PAST, "400"), ("B-2", "Ewa Nowak", PAST, "100"))
    for q in ("Anna Kowalska", "Ewa Nowak"):
        assert c.post(f"/clients/{_client_id(c, q)}/erase").status_code == 200
    from sqlalchemy import func, select

    from app.models import Client, Visit

    db = _db(c)
    assert db.scalar(select(func.count()).select_from(Client).where(Client.is_anonymous)) == 1
    assert db.scalar(select(func.count(Visit.id))) == 2


@pytest.fixture
def booksy_till(monkeypatch):
    from openpyxl import Workbook

    from app import booksy_api

    hdr = ["", "", "Data transakcji", "Numer dokumentu", "Numer rejestru", "Klient", "Pracownik",
           "Wpływy", "Wydatki", "Metoda płatności"]  # fmt: skip
    state = {"rows": []}

    def xlsx(*_a, **_k) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.append(["", "Transakcje z rejestrów kasowych"])
        ws.append(hdr)
        for i, (dt, client, inflow, *rest) in enumerate(state["rows"], 1):
            method = rest[0] if rest else "Gotówka"
            ws.append(["", str(i), dt, f"D{i}", "reg", client, "Kasjerka", inflow, "0", method])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    monkeypatch.setattr(
        booksy_api, "load_credentials", lambda db: booksy_api.BooksyCredentials("1", "t", "k", "f")
    )
    monkeypatch.setattr(booksy_api, "download_report", xlsx)
    return state


def test_a_till_resync_does_not_restore_her_name(db_client: TestClient, booksy_till) -> None:
    c = db_client
    cid = c.post("/clients", json={"first_name": "Anna", "last_name": "Kowalska"}).json()["id"]
    booksy_till["rows"] = [("12.08.2026 10:00", "Anna Kowalska", "350"),
                           ("12.08.2026 11:00", "Inna Osoba", "100")]  # fmt: skip
    body = {"date_from": PAST, "date_till": PAST}
    assert c.post("/imports/booksy/registers", json=body).status_code == 200
    c.post(f"/clients/{cid}/erase")
    assert c.post("/imports/booksy/registers", json=body).status_code == 200  # Booksy still has her

    names = [
        t["client"] for t in c.get(f"/salon-days/{PAST}/reconciliation").json()["transactions"]
    ]
    assert names == [None, "Inna Osoba"]


# ------------------------------------------------------------ review regressions
def test_live_namesake_wins(db_client: TestClient) -> None:
    """Two "Anna Nowak" in the base: erasing one must not anonymise the OTHER's
    history on a re-import, nor scrub her package or voucher (her money)."""
    from sqlalchemy import select

    from app.models import Client, Package, Visit, Voucher

    c = db_client
    a = c.post(
        "/clients", json={"first_name": "Anna", "last_name": "Nowak", "phone": "111"}
    ).json()["id"]
    b = c.post(
        "/clients", json={"first_name": "Anna", "last_name": "Nowak", "phone": "222"}
    ).json()["id"]
    db = _db(c)
    db.add_all(
        [
            Visit(client_id=a, booksy_ref="A1", service_name="Peeling", status="completed",
                  starts_at=datetime.fromisoformat(f"{PAST}T10:00:00").replace(tzinfo=UTC)),
            Visit(client_id=b, booksy_ref="B1", service_name="Peeling", status="completed",
                  starts_at=datetime.fromisoformat(f"{PAST}T12:00:00").replace(tzinfo=UTC)),
            Package(booksy_number="PA", client_id=a, client_name="Anna Nowak", name="Endermo",
                    total_value=Decimal("900"), total_treatments=10, remaining=4),
            Voucher(client_name="Anna Nowak", description="300 zł",
                    total_value=Decimal("300"), remaining_value=Decimal("300")),
        ]
    )  # fmt: skip
    db.commit()

    res = c.post(f"/clients/{b}/erase").json()
    assert res["visits_anonymised"] == 1 and res["name_suppressed"] is False

    _import(c, ("A1", "Anna Nowak", PAST, "400"), ("B1", "Anna Nowak", PAST, "150"))
    db = _db(c)
    anon = db.scalar(select(Client.id).where(Client.is_anonymous.is_(True)))
    owners = dict(db.execute(select(Visit.booksy_ref, Visit.client_id)).all())
    assert owners == {"A1": a, "B1": anon}  # hers stays hers; the erased one stays anonymous
    assert db.scalar(select(Package.client_name)) == "Anna Nowak"
    assert db.scalar(select(Voucher.client_name)) == "Anna Nowak"


def test_anonymisation_is_sticky_by_booksy_ref(db_client: TestClient) -> None:
    """Not by name or date: a booking in the future, and a client Booksy spells
    differently than our (corrected) row, must both stay anonymous on re-import."""
    c = db_client
    future = (date.today() + timedelta(days=5)).isoformat()
    _import(c, ("F1", "Ania Zielona", PAST, "100"), ("F2", "Ania Zielona", future, "120"))
    cid = _client_id(c, "Zielona")
    c.patch(f"/clients/{cid}", json={"first_name": "Anna"})  # staff fixed the spelling
    assert c.post(f"/clients/{cid}/erase").json()["visits_anonymised"] == 2

    _import(c, ("F1", "Ania Zielona", PAST, "100"), ("F2", "Ania Zielona", future, "120"))
    assert _client_id(c, "Zielona") is None  # neither spelling came back

    from sqlalchemy import func, select

    from app.models import Client, Visit

    db = _db(c)
    anon = db.scalar(select(Client.id).where(Client.is_anonymous.is_(True)))
    assert db.scalar(select(func.count(Visit.id)).where(Visit.client_id == anon)) == 2


def test_till_resync_keeps_the_package_commission(db_client: TestClient, booksy_till) -> None:
    """The redemption's value is the performer's commission base. A re-sync after the
    erasure used to re-resolve the (now nameless) row to "unmatched, 0 zł"."""
    from sqlalchemy import select

    from app.models import Package, PackageRedemption

    c = db_client
    julia = c.post("/employees", json={"display_name": "Julia", "aliases": ["Julia"]}).json()["id"]
    _import(c, ("V1", "Anna Kowalska", PAST, "0"))
    cid = _client_id(c, "Anna Kowalska")
    db = _db(c)
    db.add(Package(booksy_number="P1", client_id=cid, client_name="Anna Kowalska", name="Endermo",
                   total_value=Decimal("900"), total_treatments=10, remaining=9,
                   valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31)))  # fmt: skip
    db.commit()
    booksy_till["rows"] = [("12.08.2026 10:00", "Anna Kowalska", "0", "Pakiet")]
    body = {"date_from": PAST, "date_till": PAST}
    assert c.post("/imports/booksy/registers", json=body).status_code == 200

    def redemption():
        r = _db(c).scalar(select(PackageRedemption))
        return r.client_name, r.employee_id, r.package_id is not None, r.value

    assert redemption() == ("Anna Kowalska", julia, True, Decimal("90.00"))
    c.post(f"/clients/{cid}/erase")
    assert c.post("/imports/booksy/registers", json=body).status_code == 200
    assert redemption() == (ANON_NAME, julia, True, Decimal("90.00"))  # Julia keeps her 90 zł


def test_erased_package_is_not_linked_to_a_later_namesake(
    db_client: TestClient, monkeypatch
) -> None:
    from openpyxl import Workbook
    from sqlalchemy import select

    from app import booksy_api, packages
    from app.models import Package

    c = db_client
    _import(c, ("V1", "Anna Kowalska", PAST, "100"))
    parsed = [packages.ParsedPackage("PK1", "Anna Kowalska", "Endermo", Decimal("900"), 10, 4,
                                     date(2026, 8, 1), date(2027, 8, 1))]  # fmt: skip
    buf = io.BytesIO()
    Workbook().save(buf)
    monkeypatch.setattr(booksy_api, "load_credentials", lambda db: object())
    monkeypatch.setattr(booksy_api, "download_report", lambda *a, **k: buf.getvalue())
    monkeypatch.setattr(packages, "parse_packages_summary", lambda grid: parsed)
    assert c.post("/imports/booksy/packages").status_code == 200

    c.post(f"/clients/{_client_id(c, 'Anna Kowalska')}/erase")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    _import(c, ("V9", "Anna Kowalska", tomorrow, "200"))  # a different Anna, later
    assert c.post("/imports/booksy/packages").status_code == 200

    pkg = _db(c).scalar(select(Package))
    assert (pkg.client_name, pkg.client_id) == (ANON_NAME, None)  # not in the namesake's portal


def test_single_word_name_does_not_swallow_other_peoples_vouchers(db_client: TestClient) -> None:
    from sqlalchemy import select

    from app.models import Voucher

    c = db_client
    cid = c.post("/clients", json={"first_name": "Anna", "last_name": "?"}).json()["id"]
    db = _db(c)
    db.add_all([
        Voucher(client_name="Anna Kowalska", description="300", total_value=Decimal("300"),
                remaining_value=Decimal("300")),
        Voucher(client_name="Anna", description="100", total_value=Decimal("100"),
                remaining_value=Decimal("100")),
    ])  # fmt: skip
    db.commit()
    c.post(f"/clients/{cid}/erase")
    assert sorted(_db(c).scalars(select(Voucher.client_name))) == ["Anna Kowalska", ANON_NAME]


def test_voucher_reimport_neither_restores_the_name_nor_doubles_the_money(
    db_client: TestClient,
) -> None:
    import zipfile

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def docx(rows):
        tc = lambda t: f"<w:tc><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>"  # noqa: E731
        tbl = "".join("<w:tr>" + "".join(tc(x) for x in r) + "</w:tr>" for r in rows)
        body = f"<w:body><w:tbl>{tbl}</w:tbl></w:body>"
        xml = f'<?xml version="1.0"?><w:document xmlns:w="{w}">{body}</w:document>'
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", xml)
        return buf.getvalue()

    c = db_client
    until = (date.today() + timedelta(days=60)).strftime("%d.%m.%Y")
    raw = docx([
        ["IMIĘ NAZWISKO", "USŁUGA/KWOTA", "DATA ZAKUPU", "DATA WAŻNOŚCI", "WYKORZYSTANY"],
        ["Anna Kowalska — prezent", "300 zł", "01.08.2026", until, ""],
    ])  # fmt: skip
    upload = {"file": ("VOUCHERY.docx", raw, "application/octet-stream")}
    assert c.post("/vouchers/import", files=upload).json()["imported"] == 1
    cid = c.post("/clients", json={"first_name": "Anna", "last_name": "Kowalska"}).json()["id"]
    c.post(f"/clients/{cid}/erase")

    again = c.post("/vouchers/import", files=upload).json()
    assert (again["imported"], again["skipped_existing"]) == (0, 1)
    assert [v["client_name"] for v in c.get("/vouchers").json()] == [ANON_NAME]


def test_nothing_new_can_be_attached_to_the_placeholder(db_client: TestClient) -> None:
    from sqlalchemy import select

    from app.models import Client, Visit

    c = db_client
    _import(c, ("B-1", "Anna Kowalska", PAST, "400"))
    c.post(f"/clients/{_client_id(c, 'Anna Kowalska')}/erase")
    db = _db(c)
    anon = db.scalar(select(Client.id).where(Client.is_anonymous.is_(True)))
    visit = db.scalar(select(Visit.id).where(Visit.booksy_ref == "B-1"))
    card_type = c.get("/card-types").json()[0]["id"]
    product = c.post(
        "/shop/products", json={"name": "Krem", "price_pln": "10", "stock_qty": 1}
    ).json()

    new_visit = {"starts_at": "2026-09-01T10:00:00Z", "service_name": "X"}
    assert c.post(f"/clients/{anon}/visits", json=new_visit).status_code == 409
    # a note on an anonymised visit would re-identify it; deleting it costs commission
    assert c.patch(f"/visits/{visit}", json={"notes": "to była Anna Kowalska"}).status_code == 409
    assert c.delete(f"/visits/{visit}").status_code == 409
    assert c.put(f"/clients/{anon}/beauty-plan", json={"skin_type": "x"}).status_code == 409
    assert c.post(f"/clients/{anon}/cards", json={"card_type_id": card_type}).status_code == 409
    assert (
        c.post("/shop/sales", json={"product_id": product["id"], "client_id": anon}).status_code
        == 409
    )
    assert c.post(f"/clients/{anon}/photos/upload-url",
                  json={"content_type": "image/jpeg"}).status_code == 409  # fmt: skip


def test_customers_sync_does_not_bring_back_someone_without_a_booksy_id(
    db_client: TestClient, monkeypatch
) -> None:
    from app import booksy_api

    c = db_client
    _import(c, ("V1", "Ewa Zielona", PAST, "100"))  # created by a visit import: no Booksy id
    res = c.post(f"/clients/{_client_id(c, 'Zielona')}/erase").json()
    assert res["tombstoned"] is False

    page = {"customers": [
        {"merged_data": {"id": 777, "first_name": "Ewa", "last_name": "Zielona",
                         "cell_phone": "600100200", "email": "ewa@x.pl"}},
        {"merged_data": {"id": 778, "first_name": "Nowa", "last_name": "Klientka"}},
    ]}  # fmt: skip
    monkeypatch.setattr(
        booksy_api, "load_credentials", lambda db: booksy_api.BooksyCredentials("1", "t", "k", "f")
    )
    monkeypatch.setattr(
        booksy_api, "_get_json",
        lambda creds, url, timeout=60: page if url.endswith("page=1") else {"customers": []},
    )  # fmt: skip
    assert c.post("/imports/booksy/customers").status_code == 200
    assert _client_id(c, "Zielona") is None and _client_id(c, "Nowa Klientka") is not None


def test_erase_reports_the_cognito_login_to_remove(portal_client: TestClient) -> None:
    c = portal_client
    cid = c.post("/clients", json={"first_name": "Ewa", "last_name": "Nowak"}).json()["id"]
    code = c.post("/invites", json={"client_id": cid}).json()["code"]
    c.as_user("cognito-sub-ewa", {"client"})
    assert c.post("/invites/claim", json={"code": code}).status_code == 200
    c.as_user("test-admin", {"admin"})
    assert c.post(f"/clients/{cid}/erase").json()["cognito_accounts"] == ["cognito-sub-ewa"]
    c.as_user("cognito-sub-ewa", {"client"})
    assert c.get("/klient/me").json()["linked"] is False  # her token no longer opens a profile
    assert c.get("/klient/me/photos").status_code == 403
