"""Vouchers (gift cards): best-effort docx parse (value/dates only), manual CRUD,
partial redemption drawing down the balance with a who+when audit trail, and the
active-only docx seed."""

import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.vouchers_import import parse_vouchers_docx

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(rows: list[list[str]]) -> bytes:
    def tc(text: str) -> str:
        return f"<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"

    def tr(cells: list[str]) -> str:
        return "<w:tr>" + "".join(tc(c) for c in cells) + "</w:tr>"

    tbl = "<w:tbl>" + "".join(tr(r) for r in rows) + "</w:tbl>"
    doc = f'<?xml version="1.0"?><w:document xmlns:w="{_W}"><w:body>{tbl}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def money(v) -> Decimal:
    return Decimal(str(v))


def test_parse_vouchers_docx() -> None:
    raw = _docx(
        [
            ["IMIĘ NAZWISKO", "USŁUGA/KWOTA", "DATA ZAKUPU", "DATA WAŻNOŚCI", "WYKORZYSTANY"],
            ["Anna Nowak", "300 zł", "10.07.2026", "10.10.2026", "Wykorzystano 30.08"],
            ["Jan Kowalski", "Masaż Kobido 320zł", "01.03.24", "01.06.24", "Wykorzystano"],
            ["", "", "", "", ""],  # empty row → skipped
            ["Ewa Bok", "bez kwoty", "05.05.2026", "05.08.2026", ""],  # no value → skipped
        ]
    )
    vs = parse_vouchers_docx(raw)
    assert len(vs) == 2  # header, empty and value-less rows dropped
    assert vs[0].client_name == "Anna Nowak"
    assert vs[0].total_value == Decimal("300")
    assert vs[0].purchased_on == date(2026, 7, 10)
    assert vs[0].valid_until == date(2026, 10, 10)
    assert vs[1].total_value == Decimal("320")  # pulled from "…320zł"
    assert vs[1].purchased_on == date(2024, 3, 1)  # 2-digit year → 2024


def test_vouchers_admin_only(portal_client: TestClient) -> None:
    portal_client.as_user("staff-sub", {"staff"})
    assert portal_client.get("/vouchers").status_code == 403


def test_voucher_create_redeem_audit(db_client: TestClient) -> None:
    v = db_client.post(
        "/vouchers",
        json={"client_name": "Klientka", "description": "300 zł", "total_value": "300"},
    ).json()
    assert money(v["remaining_value"]) == money("300")  # defaults to total
    assert v["status"] == "active"

    r = db_client.post(f"/vouchers/{v['id']}/redeem", json={"amount": "120", "note": "twarz"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert money(body["remaining_value"]) == money("180")
    assert len(body["redemptions"]) == 1
    red = body["redemptions"][0]
    assert money(red["amount"]) == money("120")
    assert red["created_by"] == "test-admin"  # audit: who
    assert red["created_at"]  # audit: when

    # can't overdraw
    over = db_client.post(f"/vouchers/{v['id']}/redeem", json={"amount": "500"})
    assert over.status_code == 409

    # draw the rest → status becomes 'used'
    db_client.post(f"/vouchers/{v['id']}/redeem", json={"amount": "180"})
    used = db_client.get("/vouchers?status=used").json()
    assert any(x["id"] == v["id"] and money(x["remaining_value"]) == money("0") for x in used)


def test_voucher_import_active_only(db_client: TestClient) -> None:
    today = date.today()
    active_until = (today + timedelta(days=30)).strftime("%d.%m.%Y")
    old_until = (today - timedelta(days=400)).strftime("%d.%m.%Y")
    raw = _docx(
        [
            ["IMIĘ NAZWISKO", "USŁUGA/KWOTA", "DATA ZAKUPU", "DATA WAŻNOŚCI", "WYKORZYSTANY"],
            ["Aktywna Klientka", "250 zł", "01.01.2026", active_until, ""],
            ["Stara Klientka", "200 zł", "01.01.2024", old_until, "Wykorzystano"],
        ]
    )
    s = db_client.post(
        "/vouchers/import",
        files={"file": ("VOUCHERY.docx", raw, "application/octet-stream")},
    ).json()
    assert s["parsed"] == 2
    assert s["imported"] == 1  # only the active one
    assert s["skipped_inactive"] == 1

    rows = db_client.get("/vouchers").json()
    assert [v["client_name"] for v in rows] == ["Aktywna Klientka"]
    assert rows[0]["source"] == "docx"

    # re-import is deduped
    again = db_client.post(
        "/vouchers/import",
        files={"file": ("VOUCHERY.docx", raw, "application/octet-stream")},
    ).json()
    assert again["imported"] == 0 and again["skipped_existing"] == 1
