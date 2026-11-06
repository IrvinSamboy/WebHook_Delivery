"""Forma de las peticiones y respuestas de la API."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator

# Solo caracteres habituales, con el mismo límite de longitud que la columna en Postgres.
EventType = Annotated[
    str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
]


def _contains_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_contains_nul(k) or _contains_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_nul(item) for item in value)
    return False


class MessageIn(BaseModel):
    event_type: EventType
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def reject_nul_characters(cls, payload: dict[str, Any]) -> dict[str, Any]:
        # JSON permite \u0000, pero el tipo JSONB de PostgreSQL no puede guardarlo.
        if _contains_nul(payload):
            raise ValueError("el payload no puede contener el carácter \\u0000")
        return payload


class MessageAccepted(BaseModel):
    id: UUID


class DeliveryOut(BaseModel):
    id: UUID
    endpoint_id: UUID
    status: str
    next_attempt_at: datetime


class MessageOut(BaseModel):
    id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    deliveries: list[DeliveryOut]


class EndpointIn(BaseModel):
    url: HttpUrl
    event_types: list[EventType] = Field(min_length=1)


class EndpointCreated(BaseModel):
    id: UUID
    url: str
    event_types: list[str]
    enabled: bool
    secret: str
    created_at: datetime
