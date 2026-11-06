from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from relay.infrastructure.crypto import SecretCipher
from relay.infrastructure.db.repositories import (
    SqlAlchemyApiKeyRepository,
    SqlAlchemyApplicationRepository,
    SqlAlchemyDeliveryRepository,
    SqlAlchemyEndpointRepository,
    SqlAlchemyMessageRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session], cipher: SecretCipher) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.applications = SqlAlchemyApplicationRepository(self._session)
        self.api_keys = SqlAlchemyApiKeyRepository(self._session)
        self.endpoints = SqlAlchemyEndpointRepository(self._session, self._cipher)
        self.messages = SqlAlchemyMessageRepository(self._session)
        self.deliveries = SqlAlchemyDeliveryRepository(self._session)
        return self

    def __exit__(self, *exc_info: object) -> None:
        # Tras un commit no hay nada que deshacer; sin commit, se descarta todo.
        self._session.rollback()
        self._session.close()

    def commit(self) -> None:
        self._session.commit()
