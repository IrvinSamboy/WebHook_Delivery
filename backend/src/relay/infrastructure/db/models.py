"""Modelos ORM: cómo se guardan los datos en PostgreSQL."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from relay.domain.delivery_status import DeliveryStatus

# Nombres predecibles para las restricciones, para que Alembic pueda
# modificarlas o borrarlas en migraciones futuras.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in DeliveryStatus)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ApplicationModel(Base):
    __tablename__ = "applications"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApiKeyModel(Base):
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"))
    # La parte visible de la key: permite encontrarla sin guardarla en claro.
    prefix: Mapped[str] = mapped_column(String(20), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EndpointModel(Base):
    __tablename__ = "endpoints"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    # Indexado porque cada evento recibido busca los endpoints de su aplicación.
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    secret_encrypted: Mapped[str] = mapped_column(Text)
    event_types: Mapped[list[str]] = mapped_column(ARRAY(Text))
    enabled: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    app_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"))
    event_type: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DeliveryModel(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        # Un mensaje genera como máximo un sobre por endpoint.
        UniqueConstraint("message_id", "endpoint_id"),
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="status_valid"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id"))
    endpoint_id: Mapped[UUID] = mapped_column(ForeignKey("endpoints.id"))
    status: Mapped[str] = mapped_column(String(20))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AttemptModel(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        # Cada intento de una entrega tiene su propio número; esta restricción
        # también crea el índice para listar los intentos de una entrega.
        UniqueConstraint("delivery_id", "number", name="uq_attempts_delivery_id_number"),
        CheckConstraint("number >= 1", name="number_positive"),
        CheckConstraint("duration_ms >= 0", name="duration_not_negative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    delivery_id: Mapped[UUID] = mapped_column(ForeignKey("deliveries.id"))
    number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    request_headers: Mapped[dict[str, str]] = mapped_column(JSONB)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
