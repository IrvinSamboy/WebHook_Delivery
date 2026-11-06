"""Versiones falsas de los puertos: guardan todo en listas, sin base de datos."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from relay.domain.entities import Delivery, Endpoint, Message

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


class FakeEndpointRepository:
    def __init__(self, items: list[Endpoint]) -> None:
        self.items = items

    def add(self, endpoint: Endpoint) -> None:
        self.items.append(endpoint)

    def list_by_app(self, app_id: UUID) -> list[Endpoint]:
        return [endpoint for endpoint in self.items if endpoint.app_id == app_id]


class FakeMessageRepository:
    def __init__(self) -> None:
        self.items: list[Message] = []

    def add(self, message: Message) -> None:
        self.items.append(message)


class FakeDeliveryRepository:
    def __init__(self) -> None:
        self.items: list[Delivery] = []

    def add(self, delivery: Delivery) -> None:
        self.items.append(delivery)


class FakeUnitOfWork:
    def __init__(self, endpoints: list[Endpoint] | None = None) -> None:
        self.endpoints = FakeEndpointRepository(endpoints or [])
        self.messages = FakeMessageRepository()
        self.deliveries = FakeDeliveryRepository()
        self.committed = False

    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def commit(self) -> None:
        self.committed = True
