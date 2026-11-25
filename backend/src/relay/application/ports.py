"""Puertos: lo que los casos de uso necesitan del mundo exterior.

Son solo interfaces. Las implementaciones reales viven en infrastructure/
y las falsas, para los tests, en tests/fakes.py.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, Self
from uuid import UUID

from relay.domain.entities import (
    ApiKey,
    Application,
    Attempt,
    AttemptTrigger,
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
    `retry_after` es la espera que pidió el receptor con el header Retry-After.
    """

    status: int | None
    body: str | None
    error: str | None
    duration_ms: int
    retry_after: timedelta | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


class HttpSender(Protocol):
    """Envía un POST. Nunca lanza excepciones: los fallos vuelven en HttpResult."""

    def send(self, url: str, headers: dict[str, str], body: bytes) -> HttpResult: ...


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    # None si no se pudo contar (Redis caído): se deja pasar sin cabeceras.
    remaining: int | None
    # Segundos hasta que empieza la ventana siguiente.
    reset_seconds: int


class RateLimiter(Protocol):
    def hit(self, app_id: UUID) -> RateLimitDecision:
        """Cuenta una petición de la aplicación y dice si puede pasar."""
        ...


class DestinationGuard(Protocol):
    """Decide si se puede enviar a una URL (protección contra SSRF)."""

    def check(self, url: str) -> None:
        """Lanza DestinationNotAllowed si la URL apunta a una dirección interna."""
        ...


class TaskQueue(Protocol):
    """Avisa a los workers de que hay trabajo. Solo transporta ids y el trigger."""

    def enqueue_delivery(
        self, delivery_id: UUID, trigger: AttemptTrigger = AttemptTrigger.AUTO
    ) -> None: ...


class ApplicationRepository(Protocol):
    def add(self, application: Application) -> None: ...


class ApiKeyRepository(Protocol):
    def add(self, api_key: ApiKey) -> None: ...


class EndpointRepository(Protocol):
    def add(self, endpoint: Endpoint) -> None: ...

    def get(self, endpoint_id: UUID) -> Endpoint: ...

    def get_for_update(self, endpoint_id: UUID) -> Endpoint | None:
        """Lee el endpoint y lo bloquea hasta el final de la transacción."""
        ...

    def update(self, endpoint: Endpoint) -> None:
        """Guarda url, event_types y enabled; nunca los secretos."""
        ...

    def update_secrets(self, endpoint: Endpoint) -> None:
        """Guarda el secreto actual y el anterior con su caducidad."""
        ...

    def list_by_app(self, app_id: UUID) -> list[Endpoint]: ...


class MessageRepository(Protocol):
    def add(self, message: Message) -> None:
        """Lanza DuplicateIdempotencyKey si su key ya existe en la aplicación."""
        ...

    def get_by_idempotency_key(self, app_id: UUID, key: str) -> Message | None: ...

    def get(self, message_id: UUID) -> Message: ...


class DeliveryRepository(Protocol):
    def add(self, delivery: Delivery) -> None: ...

    def get_for_update(self, delivery_id: UUID) -> Delivery | None:
        """Lee la entrega y la bloquea hasta el final de la transacción."""
        ...

    def update(self, delivery: Delivery) -> None: ...

    def claim_due(self, now: datetime, limit: int) -> list[UUID]:
        """Pasa a queued las entregas pending cuya hora ya llegó."""
        ...

    def recover_stuck(self, older_than: timedelta) -> list[UUID]:
        """Devuelve a pending las entregas que llevan demasiado en queued o sending."""
        ...


class AttemptRepository(Protocol):
    def add(self, attempt: Attempt) -> None: ...


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
