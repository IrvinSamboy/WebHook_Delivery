"""Lecturas: van directo por SQL, sin pasar por el dominio ni los casos de uso."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.infrastructure.db.models import ApiKeyModel, DeliveryModel, MessageModel


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
                DeliveryModel.next_attempt_at,
            ).where(DeliveryModel.message_id == message_id)
        )
        .mappings()
        .all()
    )
    return {**message, "deliveries": [dict(delivery) for delivery in deliveries]}
