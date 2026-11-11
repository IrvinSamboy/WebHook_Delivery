"""Puertos: lo que los casos de uso necesitan del mundo exterior.

Son solo interfaces. Las implementaciones reales viven en infrastructure/
y las falsas, para los tests, en tests/fakes.py.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from relay.domain.entities import (
    ApiKey,
    Application,
    Attempt,
    Delivery,
    Endpoint,
    Message,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class HttpResult:
    """Lo que pasó al enviar una petición.

    Si hubo respuesta, `status` y `body` la describen. Si no la hubo,
    `error` dice por qué: "timeout", "connection_error" o "request_error".
    """

    status: int | None
    body: str | None
    error: str | None
    duration_ms: int

    @property
    def succeeded(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


class HttpSender(Protocol):
    """Envía un POST. Nunca lanza excepciones: los fallos vuelven en HttpResult."""

    def send(self, url: str, headers: dict[str, str], body: bytes) -> HttpResult: ...


class ApplicationRepository(Protocol):
    def add(self, application: Application) -> None: ...


class ApiKeyRepository(Protocol):
    def add(self, api_key: ApiKey) -> None: ...


class EndpointRepository(Protocol):
    def add(self, endpoint: Endpoint) -> None: ...

    def get(self, endpoint_id: UUID) -> Endpoint: ...

    def list_by_app(self, app_id: UUID) -> list[Endpoint]: ...


class MessageRepository(Protocol):
    def add(self, message: Message) -> None: ...

    def get(self, message_id: UUID) -> Message: ...


class DeliveryRepository(Protocol):
    def add(self, delivery: Delivery) -> None: ...

    def get_for_update(self, delivery_id: UUID) -> Delivery | None:
        """Lee la entrega y la bloquea hasta el final de la transacción."""
        ...

    def update(self, delivery: Delivery) -> None: ...


class AttemptRepository(Protocol):
    def add(self, attempt: Attempt) -> None: ...

    def count_by_delivery(self, delivery_id: UUID) -> int: ...


class UnitOfWork(Protocol):
    """Una transacción: lo escrito se guarda completo al hacer commit().

    Si se sale del bloque `with` sin commit, todo se descarta.
    """

    applications: ApplicationRepository
    api_keys: ApiKeyRepository
    endpoints: EndpointRepository
    messages: MessageRepository
    deliveries: DeliveryRepository
    attempts: AttemptRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def commit(self) -> None: ...
