"""Test environment — the same values docker compose provides, without starting any services.

Tests never connect to the database; the values only need to pass Settings validation.
Importing `app.main` does not read env (factory pattern), so the variables can be set
here, after the imports — all that matters is that they exist before the first `create_app()`.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://salon:salon@localhost:5432/salon")
os.environ.setdefault("S3_BUCKET", "salon-photos")
os.environ.setdefault("SMTP_HOST", "localhost")
os.environ.setdefault("SMTP_PORT", "1025")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:4321")


@pytest.fixture(autouse=True)
def fresh_settings() -> None:
    """Settings are cached per process — every test must see the current os.environ."""
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    # The context manager runs the lifespan — this also exercises fail-fast config validation.
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def db_client() -> TestClient:
    """TestClient with a real (in-memory SQLite) database behind get_db.

    StaticPool keeps the single :memory: database alive across sessions; schema
    comes from Base.metadata, so these tests also catch model/migration drift
    at the ORM level. Postgres-only behavior is exercised in compose, not here.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.deps import get_db
    from app.models import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    engine.dispose()
