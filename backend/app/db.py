"""Database connection — SQLAlchemy 2.x with the psycopg 3 driver."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Engine created lazily (no connection yet) and shared within the process.

    NullPool everywhere: Aurora Serverless v2 pauses to 0 ACU only when NO
    connection exists — one pooled idle connection would keep it awake 24/7
    (~$43/month, the single biggest cost foot-gun in this stack). A fresh
    connection per request costs ~ms against requests that are already rare;
    Lambda sandboxes are frozen between invocations anyway, so a pool never
    paid for itself here. Same behavior locally = same bugs locally.

    connect_timeout 30 s, not 5: the first connection after an auto-pause is
    what RESUMES the cluster (~15 s) — a short timeout would turn every wake-up
    into a spurious 503.
    """
    settings = get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        poolclass=NullPool,
        connect_args={"connect_timeout": 30},
    )
