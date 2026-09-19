"""Treatment cards + Beauty Plan (F10) — staff/admin facing.

The treatment card is the salon's WORKING record: per client and treatment type,
a session log (date, treatment/parameters or preparation, who performed it) and,
for endermologia, body measurements. It is staff-only and — by owner decision —
holds no health data: contraindications, the health interview and every signature
stay on the signed paper card; the app records only THAT the paper was signed.

The Beauty Plan is the opposite: written by the salon FOR the client (the printed
booklet's sections + a treatment plan with progress), so she reads it in her
portal (see client_portal.py).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, UserDep, require_role
from app.cards import ensure_card_types
from app.deps import get_db
from app.identity import account_for
from app.models import (
    BeautyPlan,
    BeautyPlanStep,
    CardMeasurement,
    CardSession,
    CardType,
    Client,
    ClientCard,
    Employee,
    Visit,
)
from app.rodo import ensure_real_client
from app.schemas import (
    BeautyPlanIn,
    BeautyPlanOut,
    BeautyPlanStepIn,
    BeautyPlanStepOut,
    BeautyPlanStepUpdate,
    CardMeasurementIn,
    CardMeasurementOut,
    CardSessionIn,
    CardSessionOut,
    CardSessionUpdate,
    CardTypeCreate,
    CardTypeOut,
    CardTypeUpdate,
    ClientCardCreate,
    ClientCardOut,
    ClientCardUpdate,
)


def _seeded_db(db: Annotated[Session, Depends(get_db)]) -> Session:
    ensure_card_types(db)
    return db


router = APIRouter(tags=["care"], dependencies=[require_role("staff")])

DbDep = Annotated[Session, Depends(_seeded_db)]


def _get_or_404(db: Session, model, obj_id: int, what: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found")
    return obj


def _performer_name(db: Session, user: CurrentUser) -> str:
    """Display name frozen onto the session row — the digital "podpis wykonującego"."""
    account = account_for(db, user.sub)
    if account is not None and account.employee_id is not None:
        emp = db.get(Employee, account.employee_id)
        if emp is not None:
            return emp.display_name
    return user.username


def _own_or_admin(user: CurrentUser, author_sub: str | None) -> None:
    if "admin" not in user.groups and user.sub != author_sub:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="only the author or an admin may change this entry"
        )


# ------------------------------------------------------------------ card types
@router.get("/card-types")
def list_card_types(db: DbDep) -> list[CardTypeOut]:
    rows = db.scalars(select(CardType).order_by(CardType.display_order, CardType.name)).all()
    return [CardTypeOut.model_validate(r) for r in rows]


@router.post(
    "/card-types", status_code=status.HTTP_201_CREATED, dependencies=[require_role("admin")]
)
def create_card_type(payload: CardTypeCreate, db: DbDep) -> CardTypeOut:
    n = (db.scalar(select(CardType.id).order_by(CardType.id.desc()).limit(1)) or 0) + 1
    row = CardType(code=f"custom_{n}", display_order=100 + n, **payload.model_dump())
    db.add(row)
    db.flush()
    return CardTypeOut.model_validate(row)


@router.patch("/card-types/{type_id}", dependencies=[require_role("admin")])
def update_card_type(type_id: int, payload: CardTypeUpdate, db: DbDep) -> CardTypeOut:
    row = _get_or_404(db, CardType, type_id, "card type")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.flush()
    return CardTypeOut.model_validate(row)


# ---------------------------------------------------------------- client cards
@router.get("/clients/{client_id}/cards")
def list_client_cards(client_id: int, db: DbDep) -> list[ClientCardOut]:
    _get_or_404(db, Client, client_id, "client")
    cards = db.scalars(
        select(ClientCard).where(ClientCard.client_id == client_id).order_by(ClientCard.id)
    ).all()
    return [ClientCardOut.model_validate(c) for c in cards]


@router.post("/clients/{client_id}/cards", status_code=status.HTTP_201_CREATED)
def open_client_card(
    client_id: int, payload: ClientCardCreate, user: UserDep, db: DbDep
) -> ClientCardOut:
    ensure_real_client(_get_or_404(db, Client, client_id, "client"))
    _get_or_404(db, CardType, payload.card_type_id, "card type")
    exists = db.scalar(
        select(ClientCard.id).where(
            ClientCard.client_id == client_id, ClientCard.card_type_id == payload.card_type_id
        )
    )
    if exists is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="this client already has a card of that type"
        )
    card = ClientCard(client_id=client_id, created_by=user.sub, **payload.model_dump())
    db.add(card)
    db.flush()
    return ClientCardOut.model_validate(card)


@router.patch("/cards/{card_id}")
def update_client_card(card_id: int, payload: ClientCardUpdate, db: DbDep) -> ClientCardOut:
    card = _get_or_404(db, ClientCard, card_id, "card")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(card, field, value)
    db.flush()
    return ClientCardOut.model_validate(card)


@router.delete(
    "/cards/{card_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_role("admin")],
)
def delete_client_card(card_id: int, db: DbDep) -> None:
    db.delete(_get_or_404(db, ClientCard, card_id, "card"))


# -------------------------------------------------------------------- sessions
@router.post("/cards/{card_id}/sessions", status_code=status.HTTP_201_CREATED)
def add_session(card_id: int, payload: CardSessionIn, user: UserDep, db: DbDep) -> CardSessionOut:
    card = _get_or_404(db, ClientCard, card_id, "card")
    if payload.visit_id is not None:
        visit = db.get(Visit, payload.visit_id)
        if visit is None or visit.client_id != card.client_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="visit does not belong to this client"
            )
    row = CardSession(
        card_id=card.id,
        performed_by_sub=user.sub,
        performed_by_name=_performer_name(db, user),
        **payload.model_dump(),
    )
    db.add(row)
    db.flush()
    return CardSessionOut.model_validate(row)


@router.patch("/card-sessions/{session_id}")
def update_session(
    session_id: int, payload: CardSessionUpdate, user: UserDep, db: DbDep
) -> CardSessionOut:
    row = _get_or_404(db, CardSession, session_id, "session")
    _own_or_admin(user, row.performed_by_sub)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.flush()
    return CardSessionOut.model_validate(row)


@router.delete("/card-sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, user: UserDep, db: DbDep) -> None:
    row = _get_or_404(db, CardSession, session_id, "session")
    _own_or_admin(user, row.performed_by_sub)
    db.delete(row)


# ---------------------------------------------------------------- measurements
@router.post("/cards/{card_id}/measurements", status_code=status.HTTP_201_CREATED)
def add_measurement(card_id: int, payload: CardMeasurementIn, db: DbDep) -> CardMeasurementOut:
    card = _get_or_404(db, ClientCard, card_id, "card")
    if not card.card_type.has_measurements:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="this card type does not track measurements"
        )
    row = CardMeasurement(card_id=card.id, **payload.model_dump())
    db.add(row)
    db.flush()
    return CardMeasurementOut.model_validate(row)


@router.delete("/card-measurements/{measurement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_measurement(measurement_id: int, db: DbDep) -> None:
    db.delete(_get_or_404(db, CardMeasurement, measurement_id, "measurement"))


# ----------------------------------------------------------------- beauty plan
def active_plan(db: Session, client_id: int) -> BeautyPlan | None:
    return db.scalar(
        select(BeautyPlan)
        .where(BeautyPlan.client_id == client_id, BeautyPlan.status == "active")
        .order_by(BeautyPlan.id.desc())
    )


@router.get("/clients/{client_id}/beauty-plan")
def get_beauty_plan(client_id: int, db: DbDep) -> BeautyPlanOut | None:
    _get_or_404(db, Client, client_id, "client")
    plan = active_plan(db, client_id)
    return BeautyPlanOut.model_validate(plan) if plan else None


@router.put("/clients/{client_id}/beauty-plan")
def save_beauty_plan(
    client_id: int, payload: BeautyPlanIn, user: UserDep, db: DbDep
) -> BeautyPlanOut:
    """Create the client's active plan, or replace its text sections."""
    ensure_real_client(_get_or_404(db, Client, client_id, "client"))
    plan = active_plan(db, client_id)
    if plan is None:
        plan = BeautyPlan(client_id=client_id, created_by=user.sub)
        db.add(plan)
    for field, value in payload.model_dump().items():
        setattr(plan, field, (value or "").strip() or None)
    db.flush()
    db.refresh(plan)
    return BeautyPlanOut.model_validate(plan)


@router.post("/clients/{client_id}/beauty-plan/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_beauty_plan(client_id: int, db: DbDep) -> None:
    """Close the current plan so a fresh one can be started; history is kept."""
    plan = active_plan(db, client_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no active beauty plan")
    plan.status = "archived"


@router.post("/beauty-plans/{plan_id}/steps", status_code=status.HTTP_201_CREATED)
def add_plan_step(plan_id: int, payload: BeautyPlanStepIn, db: DbDep) -> BeautyPlanStepOut:
    plan = _get_or_404(db, BeautyPlan, plan_id, "beauty plan")
    step = BeautyPlanStep(plan_id=plan.id, position=len(plan.steps), **payload.model_dump())
    db.add(step)
    db.flush()
    return BeautyPlanStepOut.model_validate(step)


@router.patch("/beauty-plan-steps/{step_id}")
def update_plan_step(step_id: int, payload: BeautyPlanStepUpdate, db: DbDep) -> BeautyPlanStepOut:
    step = _get_or_404(db, BeautyPlanStep, step_id, "plan step")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(step, field, value)
    db.flush()
    return BeautyPlanStepOut.model_validate(step)


@router.delete("/beauty-plan-steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan_step(step_id: int, db: DbDep) -> None:
    db.delete(_get_or_404(db, BeautyPlanStep, step_id, "plan step"))
