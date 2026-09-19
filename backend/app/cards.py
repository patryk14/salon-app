"""Treatment-card reference data (F10).

The salon's paper card templates, digitised once into app/data/card_types.json
(name, which session-table variant the card uses, whether it tracks body
measurements, the post-treatment recommendations). Seeded idempotently by code,
so tests (create_all) and production (migrations) end up with the same catalog,
and an owner's later edits are never overwritten.
"""

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardType

SESSION_VARIANTS = ("parameters", "preparation", "laser")


@lru_cache
def _seed() -> list[dict]:
    return json.loads((Path(__file__).parent / "data" / "card_types.json").read_text("utf-8"))


def ensure_card_types(db: Session) -> None:
    """Create any card type missing by code. Existing rows are left alone."""
    existing = set(db.scalars(select(CardType.code)).all())
    missing = [t for t in _seed() if t["code"] not in existing]
    if missing:
        db.add_all(CardType(**t) for t in missing)
        db.flush()
