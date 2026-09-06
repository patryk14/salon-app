"""Authentication/authorization — the regression guard for the open-door bug class.

The first test is the contract from the architecture plan: every route except
the health probes MUST answer 401 to an anonymous request. New routers added
without auth deps fail CI here, before they can reach a public URL.
"""

import time

from fastapi.testclient import TestClient

# Probes are token-free by design (CI smoke, ALB health checks, status badge).
# In AWS the gateway additionally guards everything but GET /healthz.
PUBLIC_PATHS = {"/healthz", "/readyz", "/openapi.json", "/docs", "/docs/oauth2-redirect"}


def _api_routes(node):
    """Recursively collect APIRoute objects — FastAPI nests included routers
    (e.g. _IncludedRouter wrappers), so a flat scan of app.routes sees none."""
    from fastapi.routing import APIRoute

    if isinstance(node, APIRoute):
        yield node
        return
    # _IncludedRouter wraps the mounted APIRouter as .original_router
    for child in getattr(node, "routes", []) or getattr(
        getattr(node, "original_router", None), "routes", []
    ):
        yield from _api_routes(child)


def test_every_route_requires_auth(auth_client: TestClient) -> None:
    checked = 0
    for route in _api_routes(auth_client.app.router):
        if route.path in PUBLIC_PATHS:
            continue
        url = route.path.replace("{client_id}", "1").replace("{visit_id}", "1")
        for method in route.methods - {"HEAD", "OPTIONS"}:
            resp = auth_client.request(method, url)
            assert resp.status_code == 401, (
                f"{method} {route.path} answered {resp.status_code} without a token — "
                "a new router is missing require_role()/auth dependencies"
            )
            checked += 1
    assert checked >= 8  # the guard itself must not silently check nothing


def test_valid_staff_token_reaches_clients(auth_client: TestClient, mint_token) -> None:
    resp = auth_client.get(
        "/clients", headers={"Authorization": f"Bearer {mint_token(groups=['staff'])}"}
    )
    assert resp.status_code == 200


def test_client_role_gets_403_not_401(auth_client: TestClient, mint_token) -> None:
    resp = auth_client.get(
        "/clients", headers={"Authorization": f"Bearer {mint_token(groups=['client'])}"}
    )
    assert resp.status_code == 403  # identity fine, role insufficient


def test_admin_passes_everything(auth_client: TestClient, mint_token) -> None:
    token = mint_token(groups=["admin"])
    assert (
        auth_client.get("/clients", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    )


def test_imports_are_admin_only(auth_client: TestClient, mint_token) -> None:
    staff = auth_client.post(
        "/imports/booksy/visits",
        headers={"Authorization": f"Bearer {mint_token(groups=['staff'])}"},
    )
    assert staff.status_code == 403


def test_expired_token_rejected(auth_client: TestClient, mint_token) -> None:
    token = mint_token(groups=["admin"], exp=int(time.time()) - 60)
    resp = auth_client.get("/clients", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_id_token_rejected(auth_client: TestClient, mint_token) -> None:
    """Only ACCESS tokens authenticate API calls — an ID token (token_use=id)
    must not, even with a valid signature."""
    token = mint_token(groups=["admin"], token_use="id")
    resp = auth_client.get("/clients", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_wrong_client_id_rejected(auth_client: TestClient, mint_token) -> None:
    token = mint_token(groups=["admin"], client_id="attacker-app")
    resp = auth_client.get("/clients", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_garbage_token_rejected(auth_client: TestClient) -> None:
    resp = auth_client.get("/clients", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401
