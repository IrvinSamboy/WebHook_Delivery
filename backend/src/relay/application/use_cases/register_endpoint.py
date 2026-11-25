from uuid import UUID, uuid4

from relay.application.ports import Clock, DestinationGuard, UnitOfWork
from relay.domain.entities import Endpoint
from relay.domain.signing import generate_secret


class RegisterEndpoint:
    def __init__(self, uow: UnitOfWork, clock: Clock, guard: DestinationGuard) -> None:
        self._uow = uow
        self._clock = clock
        self._guard = guard

    def execute(self, app_id: UUID, url: str, event_types: list[str]) -> Endpoint:
        """Lanza DestinationNotAllowed si la URL apunta a una dirección interna."""
        # Antes de abrir la transacción: resolver el DNS puede tardar.
        self._guard.check(url)
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
