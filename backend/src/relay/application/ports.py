"""Puertos: lo que los casos de uso necesitan del mundo exterior.

Son solo interfaces. Las implementaciones reales viven en infrastructure/
y las falsas, para los tests, en tests/fakes.py.
"""

from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from relay.domain.entities import ApiKey, Application, Delivery, Endpoint, Message


class Clock(Protocol):
    def now(self) -> datetime: ...


class ApplicationRepository(Protocol):
    def add(self, application: Application) -> None: ...


class ApiKeyRepository(Protocol):
    def add(self, api_key: ApiKey) -> None: ...


class EndpointRepository(Protocol):
    def add(self, endpoint: Endpoint) -> None: ...

    def list_by_app(self, app_id: UUID) -> list[Endpoint]: ...


class MessageRepository(Protocol):
    def add(self, message: Message) -> None: ...


class DeliveryRepository(Protocol):
    def add(self, delivery: Delivery) -> None: ...


class UnitOfWork(Protocol):
    """Una transacción: lo escrito se guarda completo al hacer commit().

    Si se sale del bloque `with` sin commit, todo se descarta.
    """

    applications: ApplicationRepository
    api_keys: ApiKeyRepository
    endpoints: EndpointRepository
    messages: MessageRepository
    deliveries: DeliveryRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def commit(self) -> None: ...
