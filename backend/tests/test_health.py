import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine

from app.config import Settings
from app.main import create_app
from app.routers import health


def test_healthz_returns_ok_without_db(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "salon-api"}


def test_readyz_returns_503_when_db_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Port 1 on loopback — an immediate "connection refused", no waiting for a timeout.
    dead_engine = create_engine(
        "postgresql+psycopg://x:x@127.0.0.1:1/x", connect_args={"connect_timeout": 1}
    )
    monkeypatch.setattr(health, "get_engine", lambda: dead_engine)

    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.parametrize("var", ["DATABASE_URL", "CORS_ORIGINS"])
def test_settings_require_env(var: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(var)
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_cors_allows_frontend_origin(client: TestClient) -> None:
    # The frontend (Astro on :4321) calls the API from the browser — no header, no fetch.
    response = client.get("/healthz", headers={"Origin": "http://localhost:4321"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:4321"


def test_docs_enabled_outside_prod(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_disabled_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    with TestClient(create_app()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/healthz").status_code == 200
