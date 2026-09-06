"""Booksy visits import: parser + idempotent upsert.

The fixture builds a synthetic xlsx that mimics the real export's anatomy
(title block, address, date range, header at a non-first row, footer) with
FAKE data — real reports contain personal data and never enter the repo.
"""

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


def make_report(rows: list[list]) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Lista wizyt"
    ws.append([])
    ws.append([None, "Lista wizyt"])
    ws.append([None, "Lista wizyt, powiązane szczegóły i całkowity przychód"])
    ws.append([])
    ws.append([None, "Salon Testowy, Testowa 1, Kraków"])
    ws.append([None, "Okres od 1.09.2026 do 6.09.2026"])
    ws.append([])
    ws.append([None, *HEADER])
    for row in rows:
        ws.append([None, *row])
    ws.append([None, "Suma", None, None, None, None, None, 250, 0, 200.5, 0, 46.5, 0, 250])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def visit_row(ref: int, client: str = "Anna Testowa", status: str = "Zakończone") -> list:
    return [
        "1.09.2026 08:00",
        ref,
        "Kosmetologia",
        "Peeling chemiczny",
        client,
        "Ewelina",
        "01h:00min",
        250,
        0,
        203.25,
        0,
        46.75,
        0,
        250,
        status,
    ]


def upload(db_client: TestClient, buf: io.BytesIO) -> dict:
    resp = db_client.post(
        "/imports/booksy/visits",
        files={"file": ("lista_wizyt.xlsx", buf, "application/vnd.ms-excel")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_import_creates_clients_and_visits(db_client: TestClient) -> None:
    summary = upload(
        db_client,
        make_report(
            [
                visit_row(1001),
                visit_row(1002, client="Beata Nowak-Testowa", status="Anulowane"),
                visit_row(1003, client="Anna Testowa", status="Nieobecność"),
            ]
        ),
    )
    assert summary == {
        "visits_in_file": 3,
        "clients_created": 2,  # Anna appears twice, created once
        "visits_created": 3,
        "visits_updated": 0,
    }

    clients = db_client.get("/clients", params={"q": "Nowak"}).json()
    assert clients["total"] == 1
    beata = clients["items"][0]
    assert (beata["first_name"], beata["last_name"]) == ("Beata", "Nowak-Testowa")

    anna_id = db_client.get("/clients", params={"q": "Testowa Anna"}).json()
    anna_id = db_client.get("/clients", params={"q": "Anna"}).json()["items"][0]["id"]
    visits = db_client.get(f"/clients/{anna_id}/visits").json()
    assert visits["total"] == 2
    statuses = {v["status"] for v in visits["items"]}
    assert statuses == {"completed", "no_show"}
    assert visits["items"][0]["staff_name"] == "Ewelina"
    assert visits["items"][0]["price_pln"] == "250.00"


def test_reimport_is_idempotent_and_updates(db_client: TestClient) -> None:
    upload(db_client, make_report([visit_row(2001)]))
    # Same reservation re-exported later with a changed status (cancellation).
    summary = upload(db_client, make_report([visit_row(2001, status="Anulowane")]))
    assert summary == {
        "visits_in_file": 1,
        "clients_created": 0,
        "visits_created": 0,
        "visits_updated": 1,
    }
    client_id = db_client.get("/clients").json()["items"][0]["id"]
    visits = db_client.get(f"/clients/{client_id}/visits").json()
    assert visits["total"] == 1  # no duplicate
    assert visits["items"][0]["status"] == "cancelled"


def test_import_preserves_local_notes(db_client: TestClient) -> None:
    upload(db_client, make_report([visit_row(3001)]))
    client_id = db_client.get("/clients").json()["items"][0]["id"]
    visit_id = db_client.get(f"/clients/{client_id}/visits").json()["items"][0]["id"]
    db_client.patch(f"/visits/{visit_id}", json={"notes": "skóra zareagowała dobrze"})

    upload(db_client, make_report([visit_row(3001)]))
    visit = db_client.get(f"/clients/{client_id}/visits").json()["items"][0]
    assert visit["notes"] == "skóra zareagowała dobrze"  # local field survives re-import


def test_rejects_wrong_file(db_client: TestClient) -> None:
    wb = Workbook()
    wb.active.append(["totally", "wrong", "columns"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = db_client.post(
        "/imports/booksy/visits", files={"file": ("x.xlsx", buf, "application/vnd.ms-excel")}
    )
    assert resp.status_code == 422
    assert "header row not found" in resp.json()["detail"]
