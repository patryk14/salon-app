"""Fiscal reconciliation: Booksy's till vs the fiscal printer's daily report.

The case that motivated it: a treatment settled in Booksy (165 zł) but never rung
up on the register. The day's gap equals that amount, so the system can name the
transaction — and, through the client's visit, the performer."""

import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.reconciliation import Txn, find_candidates, status_of

_HDR = ["", "", "Data transakcji", "Numer dokumentu", "Numer rejestru", "Klient", "Pracownik",
        "Wpływy", "Wydatki", "Metoda płatności"]  # fmt: skip


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["", "Transakcje z rejestrów kasowych"])
    ws.append(_HDR)
    for i, (dt, client, inflow, method) in enumerate(rows, 1):
        ws.append(
            ["", str(i), dt, f"DOC-{i}", "reg", client, "Karolina Sobas", inflow, "0", method]
        )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def booksy_till(monkeypatch):
    """Make `POST /imports/booksy/registers` return a given set of transactions."""
    from app import booksy_api

    state = {"rows": []}
    monkeypatch.setattr(
        booksy_api, "load_credentials", lambda db: booksy_api.BooksyCredentials("1", "t", "k", "f")
    )
    monkeypatch.setattr(booksy_api, "download_report", lambda *a, **k: _xlsx(state["rows"]))
    return state


def _t(amount: str, method="Gotówka", client="X") -> Txn:
    return Txn(doc=None, client=client, cashier=None, method=method, amount=Decimal(amount))


def test_candidates_single_then_pair_and_never_a_near_miss() -> None:
    txns = [_t("165"), _t("200", "Terminal płatniczy"), _t("35"), _t("0", "Pakiet")]
    assert [[t.amount for t in g] for g in find_candidates(txns, Decimal("165"))] == [[165]]
    # no single 235 → the pair that sums to it
    assert [sorted(t.amount for t in g) for g in find_candidates(txns, Decimal("235"))] == [
        [35, 200]
    ]
    assert find_candidates(txns, Decimal("166")) == []  # close is not a match
    assert find_candidates(txns, Decimal("-165")) == []  # register > Booksy: nothing to blame
    assert find_candidates(txns, Decimal("0")) == []


def test_status() -> None:
    d = Decimal
    assert status_of(None, None, None) == "no_report"
    assert status_of(d("500"), d("0"), None) == "ok"
    assert status_of(d("500"), d("165"), None) == "gap"
    assert status_of(d("500"), d("165"), d("165")) == "explained"
    # an explanation covers the AMOUNT it explained — a different gap is a new problem
    assert status_of(d("500"), d("465"), d("165")) == "gap"
    # fiscal report typed before any Booksy till exists: not a (bogus, huge) gap
    assert status_of(d("500"), d("-500"), None, has_till=False) == "not_synced"


def _set_visit(c: TestClient, visit_id: int, **values) -> None:
    """staff_name/status come from the Booksy import, not the API — set them directly."""
    from sqlalchemy import update

    from app.deps import get_db
    from app.models import Visit

    db = next(c.app.dependency_overrides[get_db]())
    db.execute(update(Visit).where(Visit.id == visit_id).values(**values))
    db.commit()


def _visit(c: TestClient, cid: int, when: str, staff: str, status: str = "completed") -> None:
    v = c.post(f"/clients/{cid}/visits", json={"starts_at": when, "service_name": "Peeling"}).json()
    _set_visit(c, v["id"], staff_name=staff, status=status)


def _sync(c: TestClient, day: str) -> None:
    r = c.post("/imports/booksy/registers", json={"date_from": day, "date_till": day})
    assert r.status_code == 200, r.text


def _close_day(c: TestClient, day: str, printer: str, **extra) -> None:
    body = {"booksy_cash": "0", "fiscal_register": "0", "fiscal_printer_total": printer, **extra}
    assert c.put(f"/salon-days/{day}", json=body).status_code == 200


DAY = "2026-09-18"


def test_julia_case_end_to_end(db_client: TestClient, booksy_till) -> None:
    c = db_client
    cid = c.post("/clients", json={"first_name": "Ewa", "last_name": "Nowak"}).json()["id"]
    _visit(c, cid, f"{DAY}T10:00:00Z", "Julia")
    booksy_till["rows"] = [
        ("18.09.2026 10:40", "Ewa Nowak", "165", "Gotówka"),
        ("18.09.2026 12:00", "Anna Inna", "250", "Terminal płatniczy"),
        ("18.09.2026 13:00", "Ola Pakietowa", "0", "Pakiet"),
    ]
    _sync(c, DAY)

    rec = c.get(f"/salon-days/{DAY}/reconciliation").json()
    assert rec["status"] == "no_report" and Decimal(rec["booksy_till"]) == Decimal("415")

    # the fiscal printer shows 250 — the 165 zł treatment was never rung up
    _close_day(c, DAY, "250")
    rec = c.get(f"/salon-days/{DAY}/reconciliation").json()
    assert rec["status"] == "gap" and Decimal(rec["gap"]) == Decimal("165")
    assert len(rec["candidates"]) == 1
    hit = rec["candidates"][0][0]
    assert (hit["client"], hit["performer"], Decimal(hit["amount"])) == (
        "Ewa Nowak", "Julia", Decimal("165"))  # fmt: skip
    month = c.get("/salon-days/reconciliation?month=2026-09").json()
    assert [(d["day"], d["status"]) for d in month] == [(DAY, "gap")]

    # a re-sync from Booksy must NOT wipe what a person typed, nor duplicate rows
    _sync(c, DAY)
    rec = c.get(f"/salon-days/{DAY}/reconciliation").json()
    assert Decimal(rec["fiscal_printer_total"]) == Decimal("250") and rec["status"] == "gap"
    assert len(rec["transactions"]) == 3


def test_explanation_is_admin_only_private_and_pinned_to_the_amount(
    portal_client: TestClient, booksy_till
) -> None:
    c = portal_client
    booksy_till["rows"] = [("18.09.2026 10:40", "Ewa Nowak", "165", "Gotówka")]
    _sync(c, DAY)
    _close_day(c, DAY, "0", note="notatka dnia")

    c.as_user("staff-x", {"staff"})
    assert (
        c.post(
            f"/salon-days/{DAY}/reconciliation/explain", json={"explained": True, "note": "x"}
        ).status_code
        == 403
    )  # staff can't wave a gap away — not even through the API

    c.as_user("test-admin", {"admin"})
    done = c.post(
        f"/salon-days/{DAY}/reconciliation/explain",
        json={"explained": True, "note": "Julia nabiła następnego dnia"},
    ).json()
    assert done["status"] == "explained" and done["recon_note"].startswith("Julia")

    # the day-close form (which knows nothing of notes) must not blank anything
    c.as_user("staff-x", {"staff"})
    _close_day(c, DAY, "0")
    day = c.get(f"/salon-days/{DAY}").json()
    assert day["note"] == "notatka dnia" and "recon_note" not in day
    rec = c.get(f"/salon-days/{DAY}/reconciliation").json()
    assert rec["status"] == "explained" and rec["recon_note"] is None  # names a colleague
    assert rec["candidates"] == [] and rec["transactions"] == []

    # a NEW un-rung treatment that day changes the gap → flagged again, not green
    c.as_user("test-admin", {"admin"})
    booksy_till["rows"].append(("18.09.2026 15:00", "Inna Klientka", "300", "Gotówka"))
    _sync(c, DAY)
    rec = c.get(f"/salon-days/{DAY}/reconciliation").json()
    assert rec["status"] == "gap" and Decimal(rec["gap"]) == Decimal("465")
    # and the explanation can be withdrawn
    back = c.post(f"/salon-days/{DAY}/reconciliation/explain", json={"explained": False}).json()
    assert back["status"] == "gap" and back["recon_note"] is None


def test_staff_cannot_hide_a_gap_by_retyping_the_booksy_till(
    portal_client: TestClient, booksy_till
) -> None:
    c = portal_client
    booksy_till["rows"] = [("18.09.2026 10:40", "Ewa Nowak", "165", "Gotówka")]
    _sync(c, DAY)
    c.as_user("staff-x", {"staff"})
    # typed "Kasa wg Booksy" = 0 to match a printer total of 0
    c.put(f"/salon-days/{DAY}", json={"booksy_cash": "0", "fiscal_register": "0",
                                      "fiscal_printer_total": "0"})  # fmt: skip
    rec = c.get(f"/salon-days/{DAY}/reconciliation").json()
    assert rec["status"] == "gap" and Decimal(rec["gap"]) == Decimal("165")  # from the kept rows


def test_report_typed_before_the_booksy_sync_is_not_a_gap(db_client: TestClient) -> None:
    _close_day(db_client, DAY, "800")
    rec = db_client.get(f"/salon-days/{DAY}/reconciliation").json()
    assert rec["status"] == "not_synced" and rec["synced"] is False
    month = db_client.get("/salon-days/reconciliation?month=2026-09").json()
    assert [d["status"] for d in month] == ["not_synced"]


def test_performer_never_guesses(db_client: TestClient, booksy_till) -> None:
    """The candidate list can put a colleague under suspicion — a cancelled visit
    must not name anyone, and two performers are both named."""
    c = db_client
    ewa = c.post("/clients", json={"first_name": "Ewa", "last_name": "Nowak"}).json()["id"]
    _visit(c, ewa, f"{DAY}T08:00:00Z", "Julia")
    _visit(c, ewa, f"{DAY}T12:00:00Z", "Oliwia", status="cancelled")
    ola = c.post("/clients", json={"first_name": "Ola", "last_name": "Dwa"}).json()["id"]
    _visit(c, ola, f"{DAY}T09:00:00Z", "Julia")
    _visit(c, ola, f"{DAY}T11:00:00Z", "Klaudia")
    booksy_till["rows"] = [
        ("18.09.2026 08:40", "ewa  NOWAK", "165", "Gotówka"),  # odd case / spacing
        ("18.09.2026 11:40", "Dwa Ola", "90", "Gotówka"),  # "Last First"
    ]
    _sync(c, DAY)
    _close_day(c, DAY, "0")
    by_client = {
        t["client"]: t["performer"]
        for t in c.get(f"/salon-days/{DAY}/reconciliation").json()["transactions"]
    }
    assert by_client == {"ewa  NOWAK": "Julia", "Dwa Ola": "Julia / Klaudia"}


def test_an_unrung_shop_sale_is_a_candidate_too(db_client: TestClient, booksy_till) -> None:
    """The gap includes shop sales, so the suspects must too — otherwise an un-rung
    PRODUCT gets pinned on an unrelated treatment of the same amount."""
    c = db_client
    emp = c.post("/employees", json={"display_name": "Julia", "fte_factor": "1.0"}).json()["id"]
    p = c.post("/shop/products", json={"name": "Krem", "price_pln": "165", "stock_qty": 3}).json()
    c.post("/shop/sales", json={"product_id": p["id"], "employee_id": emp, "sold_on": DAY})
    booksy_till["rows"] = [("18.09.2026 10:40", "Ewa Nowak", "165", "Terminal płatniczy")]
    _sync(c, DAY)
    _close_day(c, DAY, "165")  # 330 expected, 165 rung up
    rec = c.get(f"/salon-days/{DAY}/reconciliation").json()
    assert Decimal(rec["gap"]) == Decimal("165") and len(rec["candidates"]) == 2
    methods = sorted(g[0]["method"] for g in rec["candidates"])
    assert methods[0] == "Terminal płatniczy" and methods[1].startswith("sklep · Krem")
    shop_hit = next(g[0] for g in rec["candidates"] if g[0]["method"].startswith("sklep"))
    assert shop_hit["performer"] == "Julia" and shop_hit["client"] is None


def test_rodo_erase_scrubs_the_kept_till_rows(db_client: TestClient, booksy_till) -> None:
    c = db_client
    cid = c.post("/clients", json={"first_name": "Anna", "last_name": "Kowalska"}).json()["id"]
    booksy_till["rows"] = [
        ("18.09.2026 10:40", "Anna Kowalska", "350", "Terminal płatniczy"),
        ("18.09.2026 11:40", "Inna Osoba", "100", "Gotówka"),
    ]
    _sync(c, DAY)
    assert c.post(f"/clients/{cid}/erase").status_code == 200
    clients = [
        t["client"] for t in c.get(f"/salon-days/{DAY}/reconciliation").json()["transactions"]
    ]
    assert clients == [None, "Inna Osoba"]  # the amount stays (it's the till), the name goes


def test_staff_see_the_gap_but_not_who(portal_client: TestClient, booksy_till) -> None:
    c = portal_client
    booksy_till["rows"] = [("18.09.2026 10:40", "Ewa Nowak", "165", "Gotówka")]
    _sync(c, DAY)
    _close_day(c, DAY, "0")
    assert len(c.get(f"/salon-days/{DAY}/reconciliation").json()["candidates"]) == 1  # admin

    c.as_user("staff-x", {"staff"})
    rec = c.get(f"/salon-days/{DAY}/reconciliation").json()
    assert rec["status"] == "gap" and Decimal(rec["gap"]) == Decimal("165")
    assert rec["candidates"] == [] and rec["transactions"] == []
