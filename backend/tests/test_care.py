"""Treatment cards + Beauty Plan (F10).

The card is the salon's internal working record (staff-only, no health data);
the Beauty Plan is written for the client, who reads it — and the generic
aftercare text — in her portal, and nothing else from the card."""

from fastapi.testclient import TestClient


def _client(c: TestClient, first="Ola", last="Test") -> int:
    r = c.post("/clients", json={"first_name": first, "last_name": last})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _type(c: TestClient, code: str) -> dict:
    return next(t for t in c.get("/card-types").json() if t["code"] == code)


def _link_client(c: TestClient, cid: int, sub: str) -> None:
    c.as_user("test-admin", {"admin"})
    code = c.post("/invites", json={"client_id": cid}).json()["code"]
    c.as_user(sub, {"client"})
    assert c.post("/invites/claim", json={"code": code}).status_code == 200


def test_card_types_are_seeded_from_the_salon_documents(db_client: TestClient) -> None:
    types = {t["code"]: t for t in db_client.get("/card-types").json()}
    assert {"endermologia", "mezoterapia_nano", "stymulatory", "laser_iq", "inny"} <= set(types)
    assert types["endermologia"]["has_measurements"] is True
    assert types["endermologia"]["session_variant"] == "preparation"
    assert types["laser_iq"]["session_variant"] == "laser"
    assert (
        "SPF" in types["mezoterapia_nano"]["aftercare"]
        or "słońc" in (types["mezoterapia_nano"]["aftercare"])
    )
    # seeding is idempotent — a second request does not duplicate the catalog
    assert len(db_client.get("/card-types").json()) == len(types)


def test_card_with_sessions_and_audit(db_client: TestClient) -> None:
    cid = _client(db_client)
    t = _type(db_client, "mezoterapia_nano")
    card = db_client.post(
        f"/clients/{cid}/cards",
        json={
            "card_type_id": t["id"],
            "paper_signed_on": "2026-09-19",
            "contraindications_checked": True,
        },
    )
    assert card.status_code == 201, card.text
    card_id = card.json()["id"]
    # one card per treatment type
    assert (
        db_client.post(f"/clients/{cid}/cards", json={"card_type_id": t["id"]}).status_code == 409
    )

    s = db_client.post(
        f"/cards/{card_id}/sessions",
        json={
            "session_date": "2026-09-19",
            "treatment": "Nanofrax twarz",
            "parameters": "głowica 0.5 mm, 3 przejścia",
        },
    )
    assert s.status_code == 201, s.text
    assert s.json()["performed_by_name"] == "test-admin"  # the digital "podpis wykonującego"

    got = db_client.get(f"/clients/{cid}/cards").json()
    assert len(got) == 1 and got[0]["paper_signed_on"] == "2026-09-19"
    assert got[0]["contraindications_checked"] is True
    assert [x["treatment"] for x in got[0]["sessions"]] == ["Nanofrax twarz"]


def test_session_rejects_foreign_visit(db_client: TestClient) -> None:
    a, b = _client(db_client, "Anna", "A"), _client(db_client, "Beata", "B")
    card = db_client.post(
        f"/clients/{a}/cards", json={"card_type_id": _type(db_client, "inny")["id"]}
    ).json()["id"]
    vb = db_client.post(
        f"/clients/{b}/visits", json={"starts_at": "2026-09-10T10:00:00Z", "service_name": "X"}
    ).json()["id"]
    r = db_client.post(
        f"/cards/{card}/sessions", json={"session_date": "2026-09-10", "visit_id": vb}
    )
    assert r.status_code == 400


def test_measurements_only_on_cards_that_track_them(db_client: TestClient) -> None:
    cid = _client(db_client)
    ender = db_client.post(
        f"/clients/{cid}/cards", json={"card_type_id": _type(db_client, "endermologia")["id"]}
    ).json()["id"]
    peel = db_client.post(
        f"/clients/{cid}/cards", json={"card_type_id": _type(db_client, "peelingi_pca")["id"]}
    ).json()["id"]
    body = {"measured_on": "2026-09-19", "session_no": 5, "belly": "82.5", "weight": "64.0"}
    ok = db_client.post(f"/cards/{ender}/measurements", json=body)
    assert ok.status_code == 201, ok.text
    assert ok.json()["belly"] == "82.5"
    assert db_client.post(f"/cards/{peel}/measurements", json=body).status_code == 400


def test_only_author_or_admin_edits_a_session(portal_client: TestClient) -> None:
    c = portal_client
    cid = _client(c)
    card = c.post(f"/clients/{cid}/cards", json={"card_type_id": _type(c, "inny")["id"]}).json()[
        "id"
    ]
    c.as_user("staff-a", {"staff"})
    sid = c.post(f"/cards/{card}/sessions", json={"session_date": "2026-09-19"}).json()["id"]

    c.as_user("staff-b", {"staff"})
    assert c.patch(f"/card-sessions/{sid}", json={"notes": "x"}).status_code == 403
    assert c.delete(f"/card-sessions/{sid}").status_code == 403
    assert c.delete(f"/cards/{card}").status_code == 403  # deleting a whole card: admin only

    c.as_user("staff-a", {"staff"})
    assert c.patch(f"/card-sessions/{sid}", json={"notes": "poprawka"}).status_code == 200
    c.as_user("test-admin", {"admin"})
    assert c.delete(f"/card-sessions/{sid}").status_code == 204


def test_beauty_plan_sections_steps_and_archive(db_client: TestClient) -> None:
    cid = _client(db_client)
    assert db_client.get(f"/clients/{cid}/beauty-plan").json() is None

    plan = db_client.put(
        f"/clients/{cid}/beauty-plan",
        json={"skin_type": "mieszana, naczynkowa", "am_spf": "SPF 50 codziennie", "pm_serum": "  "},
    ).json()
    assert plan["skin_type"] == "mieszana, naczynkowa" and plan["pm_serum"] is None
    step = db_client.post(
        f"/beauty-plans/{plan['id']}/steps",
        json={
            "treatment": "Mezoterapia nano",
            "sessions_planned": 4,
            "interval_note": "co 3 tygodnie",
        },
    ).json()
    done = db_client.patch(f"/beauty-plan-steps/{step['id']}", json={"sessions_done": 2}).json()
    assert (done["sessions_done"], done["sessions_planned"]) == (2, 4)

    # saving again edits the SAME active plan and keeps its steps
    again = db_client.put(f"/clients/{cid}/beauty-plan", json={"skin_type": "mieszana"}).json()
    assert again["id"] == plan["id"] and len(again["steps"]) == 1
    assert again["am_spf"] is None  # PUT: what is sent is what is kept

    assert db_client.post(f"/clients/{cid}/beauty-plan/archive").status_code == 204
    assert db_client.get(f"/clients/{cid}/beauty-plan").json() is None
    fresh = db_client.put(f"/clients/{cid}/beauty-plan", json={"skin_type": "nowy"}).json()
    assert fresh["id"] != plan["id"] and fresh["steps"] == []


def test_client_sees_plan_and_aftercare_but_never_the_card(portal_client: TestClient) -> None:
    c = portal_client
    cid = _client(c)
    t = _type(c, "mezoterapia_nano")
    card = c.post(f"/clients/{cid}/cards", json={"card_type_id": t["id"], "note": "wewnętrzne"})
    c.post(
        f"/cards/{card.json()['id']}/sessions",
        json={"session_date": "2026-09-12", "parameters": "tajne parametry"},
    )
    c.put(f"/clients/{cid}/beauty-plan", json={"skin_type": "sucha"})
    other = _client(c, "Ewa", "Inna")
    c.put(f"/clients/{other}/beauty-plan", json={"skin_type": "CUDZY PLAN"})

    _link_client(c, cid, "client-sub-1")
    assert c.get("/klient/me/beauty-plan").json()["skin_type"] == "sucha"  # her own, not Ewa's
    after = c.get("/klient/me/aftercare").json()
    assert [a["treatment"] for a in after] == [t["name"]]
    assert after[0]["last_session"] == "2026-09-12"
    assert "tajne" not in str(after) and "wewnętrzne" not in str(after)
    # the staff side is closed to her
    for path in (f"/clients/{cid}/cards", "/card-types", f"/clients/{cid}/beauty-plan"):
        assert c.get(path).status_code == 403, path


def test_merge_folds_cards_and_keeps_one_active_plan(db_client: TestClient) -> None:
    c = db_client
    real, dup = _client(c, "Karolina", "Sobas"), _client(c, "Karolina Sobas", "?")
    t_same, t_other = _type(c, "mezoterapia_nano")["id"], _type(c, "laser_iq")["id"]
    real_card = c.post(f"/clients/{real}/cards", json={"card_type_id": t_same}).json()["id"]
    c.post(f"/cards/{real_card}/sessions", json={"session_date": "2026-09-01"})
    dup_same = c.post(f"/clients/{dup}/cards", json={"card_type_id": t_same}).json()["id"]
    c.post(f"/cards/{dup_same}/sessions", json={"session_date": "2026-09-08"})
    dup_other = c.post(f"/clients/{dup}/cards", json={"card_type_id": t_other}).json()["id"]
    c.post(f"/cards/{dup_other}/sessions", json={"session_date": "2026-09-09"})
    c.put(f"/clients/{real}/beauty-plan", json={"skin_type": "plan właściwy"})
    c.put(f"/clients/{dup}/beauty-plan", json={"skin_type": "plan duplikatu"})

    assert c.post(f"/clients/{dup}/merge-into/{real}").status_code == 200
    cards = {x["card_type"]["id"]: x for x in c.get(f"/clients/{real}/cards").json()}
    assert set(cards) == {t_same, t_other}
    assert len(cards[t_same]["sessions"]) == 2  # same-type sessions folded into one card
    assert len(cards[t_other]["sessions"]) == 1
    assert c.get(f"/clients/{real}/beauty-plan").json()["skin_type"] == "plan właściwy"
