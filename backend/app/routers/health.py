"""Health probes.

- /healthz — liveness: the process is alive and responding; does NOT touch the
  database, so a DB outage must not cause container restarts.
- /readyz  — readiness: the app can serve traffic (SELECT 1 against the database).
"""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "salon-api"}


@router.get("/readyz")
def readyz(response: Response) -> dict[str, str]:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        # Details go to logs only — the response must not reveal the DB host/user.
        logger.exception("readiness check failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ok"}
