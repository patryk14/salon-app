"""Database connection — SQLAlchemy 2.x with the psycopg 3 driver."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Engine created lazily (no connection yet) and shared within the process."""
    settings = get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,  # detects dropped connections (e.g. after an RDS failover)
        connect_args={"connect_timeout": 5},  # the /readyz probe must not hang forever
    )
