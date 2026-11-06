from uuid import uuid4

from relay.application.ports import Clock, UnitOfWork
from relay.domain.api_keys import generate_api_key, hash_api_key
from relay.domain.entities import ApiKey, Application


class CreateApplication:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def execute(self, name: str) -> tuple[Application, str]:
        """Devuelve la aplicación y su API key: es la única vez que la key está en claro."""
        now = self._clock.now()
        application = Application(id=uuid4(), name=name, created_at=now)
        plain_key, prefix = generate_api_key()

        with self._uow as uow:
            uow.applications.add(application)
            uow.api_keys.add(
                ApiKey(
                    id=uuid4(),
                    app_id=application.id,
                    prefix=prefix,
                    key_hash=hash_api_key(plain_key),
                    created_at=now,
                )
            )
            uow.commit()

        return application, plain_key
