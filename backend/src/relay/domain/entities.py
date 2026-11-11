"""Entidades del dominio: solo importan la librería estándar."""

from dataclasses import dataclass, field
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
class ApiKey:
    """La credencial de una aplicación; nunca contiene la key en claro."""

    id: UUID
    app_id: UUID
    prefix: str
    key_hash: str
    created_at: datetime


@dataclass(slots=True)
class Endpoint:
    """Una URL a la que una aplicación quiere que se entreguen sus eventos."""

    id: UUID
    app_id: UUID
    url: str
    secret: str = field(repr=False)  # Para que no aparezca en logs ni tracebacks.
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


# Las respuestas pueden ser enormes (una página de error HTML, por ejemplo):
# se guarda solo el principio, que basta para depurar.
RESPONSE_BODY_LIMIT = 4096


def truncate_response_body(body: str) -> str:
    """Recorta el body a RESPONSE_BODY_LIMIT bytes sin partir un carácter."""
    encoded = body.encode()
    if len(encoded) <= RESPONSE_BODY_LIMIT:
        return body
    return encoded[:RESPONSE_BODY_LIMIT].decode(errors="ignore")


@dataclass(slots=True)
class Attempt:
    """Un intento de entrega: qué se envió y qué pasó.

    Si hubo respuesta, `response_status` la describe aunque no sea 2xx.
    Si no la hubo (timeout, conexión rechazada...), `error` dice por qué.
    """

    id: UUID
    delivery_id: UUID
    number: int  # 1 para el primer intento, 2 para el primer reintento...
    started_at: datetime
    duration_ms: int
    request_headers: dict[str, str]
    response_status: int | None
    response_body: str | None
    error: str | None
