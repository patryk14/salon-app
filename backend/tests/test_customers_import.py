"""Booksy customers backfill (F7 v2): match an existing client by name (and take
Booksy's id), create the rest, and carry contacts + consents. The prep for
self-service signup (auto-link by verified email) and reminders."""


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


def test_pull_customers_matches_creates_and_carries_consents(monkeypatch) -> None:
    from sqlalchemy import select

    from app import booksy_api
    from app.models import Client

    db = _session()
    db.add(Client(first_name="Anna", last_name="Nowak"))  # existing, no id/contacts
    db.flush()

    pages = {
        1: {
            "customers": [
                {
                    "merged_data": {
                        "id": 111,
                        "first_name": "Anna",
                        "last_name": "Nowak",
                        "cell_phone": "600100200",
                        "email": "anna@x.pl",
                        "marketing_agreement": True,
                        "privacy_policy_agreement": True,
                    }
                },
                {
                    "merged_data": {
                        "id": 222,
                        "first_name": "Beata",
                        "last_name": "Kowalska",
                        "cell_phone": "600300400",
                        "email": "",
                        "marketing_agreement": False,
                        "privacy_policy_agreement": True,
                    }
                },
                {"merged_data": {"id": 333, "first_name": "", "last_name": ""}},  # nameless → skip
            ]
        },
    }
    monkeypatch.setattr(
        booksy_api, "load_credentials", lambda db: booksy_api.BooksyCredentials("1", "t", "k", "f")
    )
    monkeypatch.setattr(
        booksy_api,
        "_get_json",
        lambda creds, url, timeout=60: pages.get(int(url.split("page=")[-1]), {"customers": []}),
    )

    res = booksy_api.pull_customers(db, per_page=100)
    assert res == {
        "customers": 2,  # nameless skipped
        "created": 1,  # Beata
        "updated": 1,  # Anna matched by name
        "with_email": 1,  # only Anna had an email
        "with_phone": 2,
    }

    anna = db.scalar(select(Client).where(Client.first_name == "Anna"))
    assert anna.booksy_customer_id == 111
    assert anna.phone == "600100200" and anna.email == "anna@x.pl"
    assert anna.marketing_consent is True and anna.privacy_consent is True

    beata = db.scalar(select(Client).where(Client.first_name == "Beata"))
    assert beata is not None and beata.booksy_customer_id == 222
    assert beata.email is None  # empty string not stored
    assert beata.marketing_consent is False and beata.privacy_consent is True
    db.close()
