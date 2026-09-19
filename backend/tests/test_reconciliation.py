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
    assert status_of(None, None, False) == "no_report"
    assert status_of(Decimal("500"), Decimal("0"), False) == "ok"
    assert status_of(Decimal("500"), Decimal("165"), False) == "gap"
    assert status_of(Decimal("500"), Decimal("165"), True) == "explained"


def test_julia_case_end_to_end(db_client: TestClient, booksy_till) -> None:
    c = db_client
    day = "2026-09-18"
    # the client's visit that day names the performer (the till only names the cashier)
    cid = c.post("/clients", json={"first_name": "Ewa", "last_name": "Nowak"}).json()["id"]
    v = c.post(
        f"/clients/{cid}/visits",
        json={"starts_at": f"{day}T10:00:00Z", "service_name": "Peeling", "status": "completed"},
    ).json()
    from sqlalchemy import update

    from app.deps import get_db
    from app.models import Visit

    db = next(c.app.dependency_overrides[get_db]())
    db.execute(update(Visit).where(Visit.id == v["id"]).values(staff_name="Julia"))
    db.commit()

    booksy_till["rows"] = [
        ("18.09.2026 10:40", "Ewa Nowak", "165", "Gotówka"),
        ("18.09.2026 12:00", "Anna Inna", "250", "Terminal płatniczy"),
        ("18.09.2026 13:00", "Ola Pakietowa", "0", "Pakiet"),
    ]
    r = c.post("/imports/booksy/registers", json={"date_from": day, "date_till": day})
    assert r.status_code == 200, r.text

    # before anyone types the fiscal report there is nothing to compare
    rec = c.get(f"/salon-days/{day}/reconciliation").json()
    assert rec["status"] == "no_report" and rec["synced"] is True
    assert Decimal(rec["booksy_till"]) == Decimal("415")

    # the fiscal printer shows 250 — the 165 zł treatment was never rung up
    c.put(f"/salon-days/{day}", json={"booksy_cash": "165", "fiscal_register": "415",
                                      "fiscal_printer_total": "250"})  # fmt: skip
    rec = c.get(f"/salon-days/{day}/reconciliation").json()
    assert rec["status"] == "gap" and Decimal(rec["gap"]) == Decimal("165")
    assert len(rec["candidates"]) == 1
    hit = rec["candidates"][0][0]
    assert (hit["client"], hit["performer"], Decimal(hit["amount"])) == (
        "Ewa Nowak", "Julia", Decimal("165"))  # fmt: skip

    month = c.get("/salon-days/reconciliation?month=2026-09").json()
    assert [(d["day"], d["status"]) for d in month] == [(day, "gap")]

    # a re-sync from Booksy must NOT wipe what a person typed
    again = c.post("/imports/booksy/registers", json={"date_from": day, "date_till": day})
    assert again.status_code == 200
    rec = c.get(f"/salon-days/{day}/reconciliation").json()
    assert Decimal(rec["fiscal_printer_total"]) == Decimal("250") and rec["status"] == "gap"
    assert len(rec["transactions"]) == 3  # replaced, not duplicated

    # owner looked into it → explained (the note says why); an old-style PUT that
    # doesn't know the new fields leaves them alone
    c.put(f"/salon-days/{day}", json={"booksy_cash": "165", "fiscal_register": "415",
                                      "recon_explained": True, "note": "nabite 19.09"})  # fmt: skip
    c.put(f"/salon-days/{day}", json={"booksy_cash": "165", "fiscal_register": "415",
                                      "note": "nabite 19.09"})  # fmt: skip
    rec = c.get(f"/salon-days/{day}/reconciliation").json()
    assert rec["status"] == "explained" and Decimal(rec["fiscal_printer_total"]) == Decimal("250")


def test_staff_see_the_gap_but_not_who(portal_client: TestClient, booksy_till) -> None:
    c = portal_client
    day = "2026-09-18"
    booksy_till["rows"] = [("18.09.2026 10:40", "Ewa Nowak", "165", "Gotówka")]
    c.post("/imports/booksy/registers", json={"date_from": day, "date_till": day})
    c.put(f"/salon-days/{day}", json={"booksy_cash": "165", "fiscal_register": "165",
                                      "fiscal_printer_total": "0"})  # fmt: skip
    assert len(c.get(f"/salon-days/{day}/reconciliation").json()["candidates"]) == 1  # admin

    c.as_user("staff-x", {"staff"})
    rec = c.get(f"/salon-days/{day}/reconciliation").json()
    assert rec["status"] == "gap" and Decimal(rec["gap"]) == Decimal("165")
    assert rec["candidates"] == [] and rec["transactions"] == []
