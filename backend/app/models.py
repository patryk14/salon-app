"""ORM models — SQLAlchemy 2.0 typed declarative style.

Schema changes go through Alembic migrations (alembic/), never create_all in
production code paths. GDPR note: Client rows and Photo objects are personal
data — deletion endpoints must remove both the row and the S3 object.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow, nullable=False
    )


class Client(TimestampMixin, Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    # Phone is the natural key at the salon front desk (Booksy exports carry it too),
    # but data quality is unknown — unique is deliberately NOT enforced yet.
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    notes: Mapped[str | None] = mapped_column(Text)

    visits: Mapped[list["Visit"]] = relationship(
        back_populates="client", cascade="all, delete-orphan", passive_deletes=True
    )
    photos: Mapped[list["Photo"]] = relationship(
        back_populates="client", cascade="all, delete-orphan", passive_deletes=True
    )


class Visit(TimestampMixin, Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    service_name: Mapped[str] = mapped_column(String(200))
    # Stored as a decimal in PLN. Free-form statuses invite typos; the API layer
    # validates against VisitStatus, the column stays a plain string.
    price_pln: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    # Booksy report row identity — the idempotency key for xlsx imports:
    # re-importing the same report must update rows, not duplicate them.
    booksy_ref: Mapped[str | None] = mapped_column(String(100), unique=True)
    # "Pracownik" from the Booksy report, kept as plain text — employees are
    # not an entity in this app (Booksy owns scheduling).
    staff_name: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    client: Mapped[Client] = relationship(back_populates="visits")

    __table_args__ = (Index("ix_visits_client_starts", "client_id", "starts_at"),)


class Photo(TimestampMixin, Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id", ondelete="SET NULL"))
    # Key in the private bucket (MinIO locally, S3 in AWS). The object itself is
    # served exclusively via presigned URLs — this table never stores public links.
    s3_key: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str] = mapped_column(String(100), default="image/jpeg")
    note: Mapped[str | None] = mapped_column(Text)

    client: Mapped[Client] = relationship(back_populates="photos")
