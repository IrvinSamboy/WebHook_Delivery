"""Entidades del dominio: solo importan la librería estándar."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from relay.domain.delivery_status import DeliveryStatus


@dataclass(slots=True)
class Application:
    """Un cliente del servicio."""

    id: UUID
    name: str
    created_at: datetime


@dataclass(slots=True)
class Endpoint:
    """Una URL a la que una aplicación quiere que se entreguen sus eventos."""

    id: UUID
    app_id: UUID
    url: str
    secret: str
    event_types: list[str]
    enabled: bool
    created_at: datetime

    def accepts(self, event_type: str) -> bool:
        """Indica si este endpoint debe recibir un evento de ese tipo."""
        return self.enabled and event_type in self.event_types


@dataclass(slots=True)
class Message:
    """La carta: el evento que envió el cliente."""

    id: UUID
    app_id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(slots=True)
class Delivery:
    """El sobre: la entrega de un mensaje a un endpoint concreto."""

    id: UUID
    message_id: UUID
    endpoint_id: UUID
    status: DeliveryStatus
    next_attempt_at: datetime
    created_at: datetime
