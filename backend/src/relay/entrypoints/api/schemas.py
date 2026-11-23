"""Forma de las peticiones y respuestas de la API."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

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
    attempt_count: int
    next_attempt_at: datetime


class AttemptOut(BaseModel):
    id: UUID
    delivery_id: UUID
    endpoint_id: UUID
    number: int
    trigger: str
    started_at: datetime
    duration_ms: int
    request_headers: dict[str, str]
    response_status: int | None
    response_body: str | None
    error: str | None


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


class EndpointOut(BaseModel):
    """Un endpoint tal como se muestra al leerlo: sin el secreto."""

    id: UUID
    url: str
    event_types: list[str]
    enabled: bool
    created_at: datetime
    # Hasta cuándo se sigue firmando también con el secreto anterior a la última
    # rotación. null si nunca se rotó o si se rotó sin periodo de gracia.
    previous_secret_expires_at: datetime | None


class EndpointPatch(BaseModel):
    """Cambios parciales: solo se modifica lo que aparece en el body."""

    # Un campo desconocido (por ejemplo "secret") es un error, no se ignora:
    # el cliente creería que lo cambió.
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl | None = None
    event_types: list[EventType] | None = Field(default=None, min_length=1)
    enabled: bool | None = None

    @model_validator(mode="after")
    def check_fields(self) -> "EndpointPatch":
        if not self.model_fields_set:
            raise ValueError("indica al menos un campo: url, event_types o enabled")
        # Omitir un campo significa "no cambiarlo"; null no significa nada válido.
        nulls = [name for name in self.model_fields_set if getattr(self, name) is None]
        if nulls:
            raise ValueError(f"no pueden ser null: {', '.join(sorted(nulls))}")
        return self


class SecretRotated(BaseModel):
    """El secreto nuevo: igual que al crear el endpoint, solo se muestra esta vez."""

    id: UUID
    secret: str
    previous_secret_expires_at: datetime | None


class MessageSummary(BaseModel):
    id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class MessagePage(BaseModel):
    data: list[MessageSummary]
    # null en la última página.
    next_cursor: str | None


class EndpointStats(BaseModel):
    since: datetime
    deliveries: dict[str, int]
    # Entregas exitosas entre las terminadas (succeeded + failed); null si no hay.
    success_rate: float | None
