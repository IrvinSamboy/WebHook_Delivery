"""Lecturas: van directo por SQL, sin pasar por el dominio ni los casos de uso."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.infrastructure.db.models import (
    ApiKeyModel,
    AttemptModel,
    DeliveryModel,
    MessageModel,
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
