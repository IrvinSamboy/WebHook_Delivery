from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from relay.infrastructure.db.repositories import (
    SqlAlchemyDeliveryRepository,
    SqlAlchemyEndpointRepository,
    SqlAlchemyMessageRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.endpoints = SqlAlchemyEndpointRepository(self._session)
        self.messages = SqlAlchemyMessageRepository(self._session)
        self.deliveries = SqlAlchemyDeliveryRepository(self._session)
        return self

    def __exit__(self, *exc_info: object) -> None:
        # Tras un commit no hay nada que deshacer; sin commit, se descarta todo.
        self._session.rollback()
        self._session.close()

    def commit(self) -> None:
        self._session.commit()
