"""Versiones falsas de los puertos: guardan todo en listas, sin base de datos."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from relay.application.ports import HttpResult
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import (
    ApiKey,
    Application,
    Attempt,
    AttemptTrigger,
    Delivery,
    Endpoint,
    Message,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_endpoint(
    event_types: list[str] | None = None,
    enabled: bool = True,
    app_id: UUID | None = None,
) -> Endpoint:
    """Crea un endpoint válido; cada test solo indica lo que le importa."""
    return Endpoint(
        id=uuid4(),
        app_id=app_id or uuid4(),
        url="https://example.com/webhook",
        secret="whsec_c2VjcmV0",
        event_types=["order.paid"] if event_types is None else event_types,
        enabled=enabled,
        created_at=NOW,
    )


class FakeClock:
    """Un reloj que siempre da la misma hora, para que los tests sean repetibles."""

    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeApplicationRepository:
    def __init__(self) -> None:
        self.items: list[Application] = []

    def add(self, application: Application) -> None:
        self.items.append(application)


class FakeApiKeyRepository:
    def __init__(self) -> None:
        self.items: list[ApiKey] = []

    def add(self, api_key: ApiKey) -> None:
        self.items.append(api_key)


class FakeEndpointRepository:
    def __init__(self, items: list[Endpoint]) -> None:
        self.items = items

    def add(self, endpoint: Endpoint) -> None:
        self.items.append(endpoint)

    def get(self, endpoint_id: UUID) -> Endpoint:
        return next(e for e in self.items if e.id == endpoint_id)

    # Copias, como en FakeDeliveryRepository: lo leído no cambia hasta update().
    def get_for_update(self, endpoint_id: UUID) -> Endpoint | None:
        found = [e for e in self.items if e.id == endpoint_id]
        return replace(found[0], event_types=list(found[0].event_types)) if found else None

    def update(self, endpoint: Endpoint) -> None:
        # Como el repositorio real: solo url, event_types y enabled.
        self.items = [
            replace(e, url=endpoint.url, event_types=endpoint.event_types, enabled=endpoint.enabled)
            if e.id == endpoint.id
            else e
            for e in self.items
        ]

    def update_secrets(self, endpoint: Endpoint) -> None:
        self.items = [
            replace(
                e,
                secret=endpoint.secret,
                previous_secret=endpoint.previous_secret,
                previous_secret_expires_at=endpoint.previous_secret_expires_at,
            )
            if e.id == endpoint.id
            else e
            for e in self.items
        ]

    def list_by_app(self, app_id: UUID) -> list[Endpoint]:
        return [endpoint for endpoint in self.items if endpoint.app_id == app_id]


class FakeMessageRepository:
    def __init__(self) -> None:
        self.items: list[Message] = []

    def add(self, message: Message) -> None:
        self.items.append(message)

    def get(self, message_id: UUID) -> Message:
        return next(m for m in self.items if m.id == message_id)


class FakeDeliveryRepository:
    def __init__(self) -> None:
        self.items: list[Delivery] = []
        # La entidad no tiene updated_at: cada test dice qué entregas están
        # atascadas, y se guarda con qué antigüedad se llamó a recover_stuck.
        self.stuck: set[UUID] = set()
        self.recover_calls: list[timedelta] = []

    def add(self, delivery: Delivery) -> None:
        self.items.append(delivery)

    # Devuelven y guardan copias, como una base de datos real: cambiar el objeto
    # leído no cambia lo guardado hasta que se llama a update().
    def get_for_update(self, delivery_id: UUID) -> Delivery | None:
        found = [d for d in self.items if d.id == delivery_id]
        return replace(found[0]) if found else None

    def update(self, delivery: Delivery) -> None:
        self.items = [replace(delivery) if d.id == delivery.id else d for d in self.items]

    def claim_due(self, now: datetime, limit: int) -> list[UUID]:
        due = sorted(
            (
                d
                for d in self.items
                if d.status is DeliveryStatus.PENDING and d.next_attempt_at <= now
            ),
            key=lambda d: d.next_attempt_at,
        )[:limit]
        for delivery in due:
            delivery.status = DeliveryStatus.QUEUED
        return [d.id for d in due]

    def recover_stuck(self, older_than: timedelta) -> list[UUID]:
        self.recover_calls.append(older_than)
        rescued = [
            d
            for d in self.items
            if d.id in self.stuck and d.status in (DeliveryStatus.QUEUED, DeliveryStatus.SENDING)
        ]
        for delivery in rescued:
            delivery.status = DeliveryStatus.PENDING
            delivery.lease_id = None
        return [d.id for d in rescued]


class FakeAttemptRepository:
    def __init__(self) -> None:
        self.items: list[Attempt] = []

    def add(self, attempt: Attempt) -> None:
        self.items.append(attempt)


class FakeUnitOfWork:
    def __init__(self, endpoints: list[Endpoint] | None = None) -> None:
        self.applications = FakeApplicationRepository()
        self.api_keys = FakeApiKeyRepository()
        self.endpoints = FakeEndpointRepository(endpoints or [])
        self.messages = FakeMessageRepository()
        self.deliveries = FakeDeliveryRepository()
        self.attempts = FakeAttemptRepository()
        self.commits = 0

    @property
    def committed(self) -> bool:
        return self.commits > 0

    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1


class FakeTaskQueue:
    """Guarda los ids encolados. Con `error`, falla como si Redis estuviera caído."""

    def __init__(self, on_enqueue=None, error: Exception | None = None) -> None:
        self.enqueued: list[UUID] = []
        self.triggers: list[AttemptTrigger] = []
        self.on_enqueue = on_enqueue
        self.error = error

    def enqueue_delivery(
        self, delivery_id: UUID, trigger: AttemptTrigger = AttemptTrigger.AUTO
    ) -> None:
        if self.error:
            raise self.error
        if self.on_enqueue:
            self.on_enqueue()
        self.enqueued.append(delivery_id)
        self.triggers.append(trigger)


@dataclass
class SentRequest:
    url: str
    headers: dict[str, str]
    body: bytes


class FakeHttpSender:
    """No usa la red: guarda lo que le piden enviar y devuelve `result`.

    `on_send`, si se indica, se ejecuta en el momento del envío; sirve para
    comprobar cómo está todo justo cuando sale la petición.
    """

    def __init__(self, result: HttpResult | None = None, on_send=None) -> None:
        self.result = result or HttpResult(status=200, body="ok", error=None, duration_ms=50)
        self.on_send = on_send
        self.requests: list[SentRequest] = []

    def send(self, url: str, headers: dict[str, str], body: bytes) -> HttpResult:
        self.requests.append(SentRequest(url, headers, body))
        if self.on_send:
            self.on_send()
        return self.result
