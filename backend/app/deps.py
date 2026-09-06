"""Shared FastAPI dependencies."""

from collections.abc import Iterator

from sqlalchemy.orm import Session, sessionmaker

from app.db import get_engine


def get_db() -> Iterator[Session]:
    """One Session per request; commit on success, rollback on any exception."""
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
