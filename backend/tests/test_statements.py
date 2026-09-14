"""Bank-statement import (MT940 → expenses). The parser is pinned to the real
ING layout; import is idempotent on the bank reference; materialize groups per
(category, label) — so many Facebook charges collapse to one line — and clears
the template estimates in favor of the bank's real amounts."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.statement import parse_mt940

_MT940 = "\r\n".join(
    [
        ":20:MT940",
        ":25:/PLTEST",
        ":28C:00001",
        ":60F:C260831PLN1000,00",
        ":61:2608010801D44,00S073REF001",
        ":86:073~00MD02",
        "~20Platnosc karta",
        "~32FACEBK *ABC Dublin ~33D04",
        "~34073",
        ":61:2608050805D24,00S073REF002",
        ":86:073~00MD02",
        "~20Platnosc karta",
        "~32FACEBK *DEF Dublin ~33D04",
        "~34073",
        ":61:2608100810D216,60S041REF003",
        ":86:041~00IK01",
        "~20Platnosc BLIK",
        "~32allegro.pl WIERZBIECICE ~33Poznan",
        "~34041",
        ":61:2608040804D5024,00S020REF004",
        ":86:020~00IBCG",
        "~20Wynagrodzenie Lipiec",
        "~32Julia Kaniewska ul.~33Zeromskiego",
        "~34020",
        ":61:2608070807C2110,43S034REF005",
        ":86:034~00EXGC",
        "~20/OPF/X/",
        "~32FISERV POLSKA ~33AKCYJNA",
        "~34034",
        ":62F:C260831PLN2000,00",
        "-",
    ]
).encode("cp852")


def test_parse_mt940() -> None:
    txns = parse_mt940(_MT940)
    assert len(txns) == 4  # the credit (FISERV) is skipped — revenue side

    fb = txns[0]
    assert fb.value_date == date(2026, 8, 1)
    assert fb.amount == Decimal("44.00")
    assert fb.suggested_category == "koszty_zmienne"
    assert fb.suggested_name == "Reklama Facebook"
    assert fb.bucket == "operating"

    allegro = txns[2]
    assert allegro.suggested_category is None  # aggregator → manual review
    assert allegro.bucket == "unknown"

    salary = txns[3]
    assert salary.bucket == "staff"  # ignored: staff cost comes from settlements
    assert salary.suggested_category is None

    assert len({t.bank_ref for t in txns}) == 4  # refs are the dedup key


def test_statements_admin_only(portal_client: TestClient) -> None:
    portal_client.as_user("staff-sub", {"staff"})
    assert portal_client.get("/statements?month=2026-08").status_code == 403


def _upload(client: TestClient):
    return client.post(
        "/statements/import",
        files={"file": ("aug.sta", _MT940, "application/octet-stream")},
    )


def test_import_dedup_review_and_materialize(db_client: TestClient) -> None:
    r = _upload(db_client)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s == {
        "year_month": "2026-08",
        "parsed": 4,
        "added": 4,
        "duplicates": 0,
        "needs_review": 1,  # only the Allegro row (staff is auto-ignored)
    }

    rows = db_client.get("/statements?month=2026-08").json()
    assert len(rows) == 4
    by_ref = {row["name"]: row for row in rows}
    assert by_ref["Wynagrodzenie"]["status"] == "ignored"  # staff, pre-ignored
    allegro = next(row for row in rows if row["counterparty"].lower().startswith("allegro"))
    assert allegro["category"] is None

    # assign the aggregator to a real category
    db_client.put(f"/statements/{allegro['id']}", json={"category": "kosmetologia"})

    m = db_client.post("/statements/materialize?month=2026-08").json()
    assert m["expenses_created"] == 2  # Facebook (grouped) + Allegro
    assert m["txns_imported"] == 3  # 2 Facebook + 1 Allegro (salary stays ignored)
    assert m["unassigned"] == 0

    p = db_client.get("/pnl/2026-08").json()
    cats = {c["code"]: c for c in p["categories"]}
    assert Decimal(str(cats["koszty_zmienne"]["total"])) == Decimal("68")  # 44 + 24 in ONE line
    assert len(cats["koszty_zmienne"]["lines"]) == 1
    assert Decimal(str(cats["kosmetologia"]["total"])) == Decimal("216.60")

    # re-import is idempotent (bank refs already seen) …
    again = _upload(db_client).json()
    assert again["added"] == 0 and again["duplicates"] == 4
    # … and re-materialize does nothing (rows already imported)
    m2 = db_client.post("/statements/materialize?month=2026-08").json()
    assert m2["expenses_created"] == 0 and m2["txns_imported"] == 0


def test_materialize_clears_recurring_estimates(db_client: TestClient) -> None:
    # a template estimate gets prefilled when the month opens …
    db_client.post(
        "/expenses/recurring",
        json={"category_code": "koszty_stale", "name": "ZUS", "amount_pln": "1800"},
    )
    p = db_client.get("/pnl/2026-08").json()
    assert any(line["name"] == "ZUS" for line in p["categories"][0]["lines"])

    # … and importing the bank statement replaces estimates with real amounts
    _upload(db_client)
    m = db_client.post("/statements/materialize?month=2026-08").json()
    assert m["recurring_cleared"] == 1

    p2 = db_client.get("/pnl/2026-08").json()
    stale = next(c for c in p2["categories"] if c["code"] == "koszty_stale")
    assert not any(line["source"] == "recurring" for line in stale["lines"])
