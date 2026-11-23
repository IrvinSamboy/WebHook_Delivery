"""Lecturas: van directo por SQL, sin pasar por el dominio ni los casos de uso."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from relay.domain.delivery_status import DeliveryStatus
from relay.infrastructure.db.models import (
    ApiKeyModel,
    AttemptModel,
    DeliveryModel,
    EndpointModel,
    MessageModel,
)

# Las columnas que se pueden mostrar: nunca el secreto.
_ENDPOINT_COLUMNS = (
    EndpointModel.id,
    EndpointModel.url,
    EndpointModel.event_types,
    EndpointModel.enabled,
    EndpointModel.created_at,
    EndpointModel.previous_secret_expires_at,
)


def find_api_key(session: Session, prefix: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            select(ApiKeyModel.app_id, ApiKeyModel.key_hash).where(ApiKeyModel.prefix == prefix)
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_message(session: Session, app_id: UUID, message_id: UUID) -> dict[str, Any] | None:
    """Devuelve el mensaje con sus entregas, solo si pertenece a esa aplicación."""
    message = (
        session.execute(
            select(
                MessageModel.id,
                MessageModel.event_type,
                MessageModel.payload,
                MessageModel.created_at,
            ).where(MessageModel.id == message_id, MessageModel.app_id == app_id)
        )
        .mappings()
        .first()
    )
    if message is None:
        return None

    deliveries = (
        session.execute(
            select(
                DeliveryModel.id,
                DeliveryModel.endpoint_id,
                DeliveryModel.status,
                DeliveryModel.attempt_count,
                DeliveryModel.next_attempt_at,
            ).where(DeliveryModel.message_id == message_id)
        )
        .mappings()
        .all()
    )
    return {**message, "deliveries": [dict(delivery) for delivery in deliveries]}


def list_attempts(session: Session, app_id: UUID, message_id: UUID) -> list[dict[str, Any]] | None:
    """Los intentos de todas las entregas del mensaje, en orden de envío.

    Devuelve None si el mensaje no existe o es de otra aplicación, y [] si
    existe pero todavía no tiene intentos.
    """
    exists = session.scalar(
        select(MessageModel.id).where(MessageModel.id == message_id, MessageModel.app_id == app_id)
    )
    if exists is None:
        return None

    rows = session.execute(
        select(
            AttemptModel.id,
            AttemptModel.delivery_id,
            DeliveryModel.endpoint_id,
            AttemptModel.number,
            AttemptModel.trigger,
            AttemptModel.started_at,
            AttemptModel.duration_ms,
            AttemptModel.request_headers,
            AttemptModel.response_status,
            AttemptModel.response_body,
            AttemptModel.error,
        )
        .join(DeliveryModel, DeliveryModel.id == AttemptModel.delivery_id)
        .where(DeliveryModel.message_id == message_id)
        .order_by(AttemptModel.started_at, AttemptModel.number)
    ).mappings()
    return [dict(row) for row in rows]


def list_endpoints(session: Session, app_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        select(*_ENDPOINT_COLUMNS)
        .where(EndpointModel.app_id == app_id)
        .order_by(EndpointModel.created_at, EndpointModel.id)
    ).mappings()
    return [dict(row) for row in rows]


def get_endpoint(session: Session, app_id: UUID, endpoint_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            select(*_ENDPOINT_COLUMNS).where(
                EndpointModel.id == endpoint_id, EndpointModel.app_id == app_id
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_messages(
    session: Session,
    app_id: UUID,
    limit: int,
    before: tuple[datetime, UUID] | None = None,
    event_type: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Una página de mensajes, del más nuevo al más viejo.

    `before` es la posición (created_at, id) del último mensaje de la página
    anterior. Devuelve los mensajes y si quedan más.
    """
    query = (
        select(
            MessageModel.id,
            MessageModel.event_type,
            MessageModel.payload,
            MessageModel.created_at,
        )
        .where(MessageModel.app_id == app_id)
        .order_by(MessageModel.created_at.desc(), MessageModel.id.desc())
        # Uno de más: si llega, hay otra página. Más barato que un COUNT(*).
        .limit(limit + 1)
    )
    if before is not None:
        # Compara la pareja: primero la hora y, si empata, el id.
        query = query.where(tuple_(MessageModel.created_at, MessageModel.id) < tuple_(*before))
    if event_type is not None:
        query = query.where(MessageModel.event_type == event_type)

    rows = [dict(row) for row in session.execute(query).mappings()]
    return rows[:limit], len(rows) > limit


STATS_WINDOW = timedelta(hours=24)


def endpoint_stats(session: Session, app_id: UUID, endpoint_id: UUID) -> dict[str, Any] | None:
    """Entregas del endpoint creadas en las últimas 24 h, por estado.

    Devuelve None si el endpoint no existe o es de otra aplicación.
    """
    exists = session.scalar(
        select(EndpointModel.id).where(
            EndpointModel.id == endpoint_id, EndpointModel.app_id == app_id
        )
    )
    if exists is None:
        return None

    since = session.scalar(select(func.now() - STATS_WINDOW))
    counts = {status.value: 0 for status in DeliveryStatus}
    rows = session.execute(
        select(DeliveryModel.status, func.count())
        .where(DeliveryModel.endpoint_id == endpoint_id, DeliveryModel.created_at >= since)
        .group_by(DeliveryModel.status)
    )
    for status, count in rows:
        counts[status] = count

    # Solo cuentan las terminadas: una pending todavía puede salir bien.
    finished = counts["succeeded"] + counts["failed"]
    return {
        "since": since,
        "deliveries": counts,
        "success_rate": None if finished == 0 else round(counts["succeeded"] / finished, 4),
    }
