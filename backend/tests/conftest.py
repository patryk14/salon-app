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
# Tests never talk to Cognito: tokens are minted with a local RSA key and the
# JWKS lookup is monkeypatched (see auth_keys fixture). The issuer value only
# has to be internally consistent.
os.environ.setdefault("AUTH_ISSUER", "https://test-issuer.invalid")
os.environ.setdefault("AUTH_AUDIENCE", "test-client-id")


@pytest.fixture(autouse=True)
def fresh_settings() -> None:
    """Settings are cached per process — every test must see the current os.environ."""
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    # The context manager runs the lifespan — this also exercises fail-fast config validation.
    with TestClient(create_app()) as c:
        yield c


def _sqlite_db_override():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

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

    return engine, override_get_db


@pytest.fixture
def db_client() -> TestClient:
    """TestClient with in-memory SQLite behind get_db AND auth overridden to an
    admin identity — domain tests exercise CRUD/import logic, not authn (that
    has its own suite in test_auth.py against the real dependency chain).

    StaticPool keeps the single :memory: database alive across sessions; schema
    comes from Base.metadata, so these tests also catch model/migration drift
    at the ORM level. Postgres-only behavior is exercised in compose, not here.
    """
    from app.auth import CurrentUser, get_current_user
    from app.deps import get_db

    engine, override_get_db = _sqlite_db_override()
    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="test-admin", username="test-admin", groups=frozenset({"admin"})
    )
    with TestClient(app) as c:
        yield c
    engine.dispose()


@pytest.fixture
def portal_client() -> TestClient:
    """Like db_client but the current identity is SWAPPABLE via `c.as_user(...)`
    over one shared in-memory DB — F6 tests act as admin (create an invite), then
    as a specific staff `sub` (claim it, read /me). Starts as admin."""
    from app.auth import CurrentUser, get_current_user
    from app.deps import get_db

    engine, override_get_db = _sqlite_db_override()
    app = create_app()
    holder = {
        "user": CurrentUser(sub="test-admin", username="test-admin", groups=frozenset({"admin"}))
    }
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: holder["user"]

    with TestClient(app) as c:

        def as_user(sub: str, groups: set[str]) -> None:
            holder["user"] = CurrentUser(sub=sub, username=sub, groups=frozenset(groups))

        c.as_user = as_user  # type: ignore[attr-defined]
        yield c
    engine.dispose()


@pytest.fixture(scope="session")
def rsa_keys():
    """One RSA keypair per test session — minting keys is slow, reuse is safe."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def auth_client(rsa_keys, monkeypatch) -> TestClient:
    """TestClient with the REAL auth dependency chain: tokens are validated by
    app.auth.decode_token, only the JWKS network lookup is replaced with the
    session keypair. Use `mint_token` to produce Bearer tokens."""
    from app import auth as auth_module
    from app.deps import get_db

    class _FakeJwk:
        def __init__(self, key):
            self.key_id = "test-kid"
            self.key = key

    class _FakeJwkSet:
        def __init__(self, key):
            self.keys = [_FakeJwk(key)]

    class _FakeJwksClient:
        def __init__(self, public_key):
            self._set = _FakeJwkSet(public_key)

        def get_jwk_set(self, refresh: bool = False):
            return self._set

    auth_module._jwks_client.cache_clear()
    monkeypatch.setattr(auth_module, "_jwks_client", lambda: _FakeJwksClient(rsa_keys[1]))

    engine, override_get_db = _sqlite_db_override()
    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    engine.dispose()


@pytest.fixture
def mint_token(rsa_keys):
    """Factory for Cognito-shaped ACCESS tokens signed with the test key."""
    import time

    import jwt as pyjwt

    def _mint(groups: list[str] | None = None, **overrides):
        now = int(time.time())
        claims = {
            "sub": "00000000-test-sub",
            "iss": os.environ["AUTH_ISSUER"],
            "client_id": os.environ["AUTH_AUDIENCE"],
            "token_use": "access",
            "username": "test-user",
            "cognito:groups": groups or [],
            "iat": now,
            "exp": now + 300,
        }
        claims.update(overrides)
        return pyjwt.encode(claims, rsa_keys[0], algorithm="RS256", headers={"kid": "test-kid"})

    return _mint
