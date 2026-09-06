"""Layer-2 authentication/authorization — the app is the authority.

API Gateway's JWT authorizer (layer 1) already rejects anonymous traffic in
AWS, but the app re-validates every token itself: signature against the
issuer's JWKS, expiry, token_use and client id. That keeps compose and the
EKS lab exactly as secure as Lambda, and the gateway merely a cost moat.

Cognito ACCESS tokens carry no `aud` claim — the client id lives in
`client_id`, and roles arrive in `cognito:groups`. ID tokens are deliberately
rejected (`token_use` must be "access"): the access token is what a client
presents to an API.
"""

import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.config import get_settings

ALGORITHM = "RS256"

# A JWKS refetch may be forced at most this often. The kid in a JWT header is
# attacker-controlled (read before signature verification!) — without a
# cooldown, garbage kids would turn every request into a blocking HTTPS call
# to the issuer (threadpool exhaustion + traffic amplification). Cognito
# rotates keys rarely; one minute of "unknown kid" during a rotation is fine.
_REFRESH_COOLDOWN_S = 60.0
_refresh_lock = threading.Lock()
_last_refresh = 0.0


@dataclass(frozen=True)
class CurrentUser:
    sub: str
    username: str
    groups: frozenset[str] = field(default_factory=frozenset)

    def has_role(self, *roles: str) -> bool:
        # admin is a superset of every role by policy.
        return "admin" in self.groups or any(r in self.groups for r in roles)


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    """One JWKS client per process. Deliberately NO cache_keys: its per-kid LRU
    has no TTL, so a rotated-out (possibly compromised) key would stay trusted
    until process restart. The JWK-set cache (5 min lifespan) is the only tier —
    a revoked key stops validating within minutes."""
    issuer = get_settings().auth_issuer
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=False, timeout=3)


def _signing_key_for(kid: str):
    """Resolve kid against the CACHED key set; refresh over the network at most
    once per cooldown window (see _REFRESH_COOLDOWN_S). PyJWKClient's own
    get_signing_key refreshes unconditionally on a miss — an attacker-paced
    network call we refuse to make."""
    global _last_refresh
    client = _jwks_client()
    keys = {k.key_id: k for k in client.get_jwk_set().keys}
    if kid in keys:
        return keys[kid]
    with _refresh_lock:
        now = time.monotonic()
        if now - _last_refresh >= _REFRESH_COOLDOWN_S:
            _last_refresh = now
            keys = {k.key_id: k for k in client.get_jwk_set(refresh=True).keys}
            if kid in keys:
                return keys[kid]
    raise jwt.InvalidTokenError("unknown signing key")


def decode_token(token: str) -> CurrentUser:
    """Validate a Cognito access token; raises jwt exceptions on any failure."""
    settings = get_settings()
    kid = jwt.get_unverified_header(token).get("kid")
    if not kid:
        raise jwt.InvalidTokenError("missing kid")
    signing_key = _signing_key_for(kid)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=[ALGORITHM],
        issuer=settings.auth_issuer,
        # Access tokens have no aud claim — audience is enforced via client_id below.
        options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
    )
    if claims.get("token_use") != "access":
        raise jwt.InvalidTokenError("not an access token")
    if claims.get("client_id") != settings.auth_audience:
        raise jwt.InvalidTokenError("wrong client_id")
    return CurrentUser(
        sub=claims["sub"],
        username=claims.get("username", claims["sub"]),
        groups=frozenset(claims.get("cognito:groups", [])),
    )


def get_current_user(request: Request) -> CurrentUser:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(token)
    except jwt.PyJWKClientConnectionError as e:
        # Issuer unreachable is OUR outage, not the caller's bad token —
        # 503 keeps retries/alerts honest (a 401 here would gaslight clients).
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="auth backend unavailable"
        ) from e
    except jwt.PyJWTError as e:
        # The class of failure goes to the client; specifics stay out of responses.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


UserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(*roles: str):
    """Router-level guard: authenticated AND holding one of the roles (admin
    always passes). 401 without identity, 403 with the wrong one — the
    difference matters for clients and for debugging."""

    def checker(user: UserDep) -> CurrentUser:
        if not user.has_role(*roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return user

    return Depends(checker)
