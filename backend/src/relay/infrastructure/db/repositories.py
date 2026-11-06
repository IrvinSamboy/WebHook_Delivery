"""Repositorios: convierten entre entidades del dominio y modelos ORM.

Cada add() hace flush para enviar el INSERT en ese momento, dentro de la
transacción. Los modelos no declaran relationship(), así que SQLAlchemy no
ordena solo los INSERT: el orden es el mismo en que se llama a add(), y un
mensaje debe insertarse antes que sus entregas.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.domain.entities import Delivery, Endpoint, Message
from relay.infrastructure.db.models import DeliveryModel, EndpointModel, MessageModel


class SqlAlchemyEndpointRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, endpoint: Endpoint) -> None:
        self._session.add(
            EndpointModel(
                id=endpoint.id,
                app_id=endpoint.app_id,
                url=endpoint.url,
                secret=endpoint.secret,
                event_types=endpoint.event_types,
                enabled=endpoint.enabled,
                created_at=endpoint.created_at,
            )
        )
        self._session.flush()

    def list_by_app(self, app_id: UUID) -> list[Endpoint]:
        models = self._session.scalars(
            select(EndpointModel).where(EndpointModel.app_id == app_id)
        )
        return [_endpoint_to_entity(model) for model in models]


class SqlAlchemyMessageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, message: Message) -> None:
        self._session.add(
            MessageModel(
                id=message.id,
                app_id=message.app_id,
                event_type=message.event_type,
                payload=message.payload,
                created_at=message.created_at,
            )
        )
        self._session.flush()


class SqlAlchemyDeliveryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, delivery: Delivery) -> None:
        self._session.add(
            DeliveryModel(
                id=delivery.id,
                message_id=delivery.message_id,
                endpoint_id=delivery.endpoint_id,
                status=delivery.status.value,
                next_attempt_at=delivery.next_attempt_at,
                created_at=delivery.created_at,
            )
        )
        self._session.flush()


def _endpoint_to_entity(model: EndpointModel) -> Endpoint:
    return Endpoint(
        id=model.id,
        app_id=model.app_id,
        url=model.url,
        secret=model.secret,
        event_types=list(model.event_types),
        enabled=model.enabled,
        created_at=model.created_at,
    )
