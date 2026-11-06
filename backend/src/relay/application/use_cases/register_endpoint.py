from uuid import UUID, uuid4

from relay.application.ports import Clock, UnitOfWork
from relay.domain.entities import Endpoint
from relay.domain.signing import generate_secret


class RegisterEndpoint:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def execute(self, app_id: UUID, url: str, event_types: list[str]) -> Endpoint:
        endpoint = Endpoint(
            id=uuid4(),
            app_id=app_id,
            url=url,
            secret=generate_secret(),
            event_types=event_types,
            enabled=True,
            created_at=self._clock.now(),
        )

        with self._uow as uow:
            uow.endpoints.add(endpoint)
            uow.commit()

        return endpoint
