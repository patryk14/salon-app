"""API request/response shapes (Pydantic). ORM rows never leave the app raw."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class VisitStatus(StrEnum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


# --------------------------------------------------------------------- clients
class ClientCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    notes: str | None = None


class ClientUpdate(BaseModel):
    """PATCH semantics: only provided fields change."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    notes: str | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    phone: str | None
    email: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------- visits
class VisitCreate(BaseModel):
    starts_at: datetime
    service_name: str = Field(min_length=1, max_length=200)
    price_pln: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    status: VisitStatus = VisitStatus.scheduled
    notes: str | None = None


class VisitUpdate(BaseModel):
    starts_at: datetime | None = None
    service_name: str | None = Field(default=None, min_length=1, max_length=200)
    price_pln: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=2)
    status: VisitStatus | None = None
    notes: str | None = None


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    starts_at: datetime
    service_name: str
    price_pln: Decimal | None
    status: VisitStatus
    booksy_ref: str | None
    staff_name: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ pagination
class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
