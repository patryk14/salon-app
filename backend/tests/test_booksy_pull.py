"""Automatic Booksy pull (F5). The live Booksy call (download_report) is
monkeypatched to synthetic xlsx bytes, so the download→parse→upsert pipeline is
tested end-to-end without touching Booksy."""

import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

HEADER = [
    "Data i godzina",
    "ID rezerwacji",
    "Kategoria główna",
    "Usługa",
    "Klient",
    "Pracownik",
    "Czas trwania usługi",
    "Wartość usług",
    "Wartość dodatków",
    "Przychód netto",
    "Rabat",
    "Podatek",
    "Napiwek",
    "Przychód",
    "Status",
]


def visits_report_bytes(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Lista wizyt"
    for _ in range(7):
        ws.append([])
    ws.append([None, *HEADER])
    for r in rows:
        ws.append([None, *r])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(ref: int, client: str, staff: str, price: str, status: str = "Zakończone") -> list:
    return [
        "1.09.2026 10:00",
        ref,
        "Kosmetologia",
        "Peeling",
        client,
        staff,
        "01h",
        price,
        0,
        price,
        0,
        0,
        0,
        price,
        status,
    ]


def _set_creds(db_client: TestClient) -> None:
    r = db_client.put(
        "/imports/booksy/credentials",
        json={
            "business_id": "221497",
            "access_token": "tok",
            "api_key": "key",
            "fingerprint": "fp",
        },
    )
    assert r.status_code == 204, r.text


def test_pull_downloads_and_upserts(db_client: TestClient, monkeypatch) -> None:
    _set_creds(db_client)
    data = visits_report_bytes([_row(5001, "Anna Testowa", "Ewelina", "250")])
    import app.booksy_api as api

    monkeypatch.setattr(api, "download_report", lambda *a, **k: data)

    r = db_client.post(
        "/imports/booksy/pull",
        json={"report_key": "appointments", "date_from": "2026-09-01", "date_till": "2026-09-30"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["visits_created"] == 1
    # the pulled visit is now queryable like any imported one
    clients = db_client.get("/clients", params={"q": "Testowa"}).json()
    assert clients["total"] == 1


def test_pull_without_credentials_is_502(db_client: TestClient) -> None:
    r = db_client.post(
        "/imports/booksy/pull",
        json={"report_key": "appointments", "date_from": "2026-09-01", "date_till": "2026-09-30"},
    )
    assert r.status_code == 502
    assert "poświadcze" in r.json()["detail"]


def test_pull_with_expired_token_is_502(db_client: TestClient, monkeypatch) -> None:
    _set_creds(db_client)
    import app.booksy_api as api

    def boom(*a, **k):
        raise api.BooksyAuthError("Booksy odrzucił poświadczenia — token wygasł, odśwież")

    monkeypatch.setattr(api, "download_report", boom)
    r = db_client.post(
        "/imports/booksy/pull",
        json={"report_key": "appointments", "date_from": "2026-09-01", "date_till": "2026-09-30"},
    )
    assert r.status_code == 502
    assert "wygasł" in r.json()["detail"]


def test_credentials_and_pull_require_admin(auth_client: TestClient, mint_token) -> None:
    staff = {"Authorization": f"Bearer {mint_token(groups=['staff'])}"}
    assert (
        auth_client.put(
            "/imports/booksy/credentials",
            headers=staff,
            json={"business_id": "1", "access_token": "a", "api_key": "b", "fingerprint": "c"},
        ).status_code
        == 403
    )
