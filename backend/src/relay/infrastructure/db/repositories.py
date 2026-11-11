"""Repositorios: convierten entre entidades del dominio y modelos ORM.

Cada add() hace flush para enviar el INSERT en ese momento, dentro de la
transacción. Los modelos no declaran relationship(), así que SQLAlchemy no
ordena solo los INSERT: el orden es el mismo en que se llama a add(), y un
mensaje debe insertarse antes que sus entregas.
"""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import (
    ApiKey,
    Application,
    Attempt,
    Delivery,
    Endpoint,
    Message,
)
from relay.infrastructure.crypto import SecretCipher
from relay.infrastructure.db.models import (
    ApiKeyModel,
    ApplicationModel,
    AttemptModel,
    DeliveryModel,
    EndpointModel,
    MessageModel,
)


class SqlAlchemyApplicationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, application: Application) -> None:
        self._session.add(
            ApplicationModel(
                id=application.id,
                name=application.name,
                created_at=application.created_at,
            )
        )
        self._session.flush()


class SqlAlchemyApiKeyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, api_key: ApiKey) -> None:
        self._session.add(
            ApiKeyModel(
                id=api_key.id,
                app_id=api_key.app_id,
                prefix=api_key.prefix,
                key_hash=api_key.key_hash,
                created_at=api_key.created_at,
            )
        )
        self._session.flush()


class SqlAlchemyEndpointRepository:
    def __init__(self, session: Session, cipher: SecretCipher) -> None:
        self._session = session
        self._cipher = cipher

    def add(self, endpoint: Endpoint) -> None:
        self._session.add(
            EndpointModel(
                id=endpoint.id,
                app_id=endpoint.app_id,
                url=endpoint.url,
                secret_encrypted=self._cipher.encrypt(endpoint.secret),
                event_types=endpoint.event_types,
                enabled=endpoint.enabled,
                created_at=endpoint.created_at,
            )
        )
        self._session.flush()

    def get(self, endpoint_id: UUID) -> Endpoint:
        return self._to_entity(self._session.get_one(EndpointModel, endpoint_id))

    def list_by_app(self, app_id: UUID) -> list[Endpoint]:
        models = self._session.scalars(
            select(EndpointModel).where(EndpointModel.app_id == app_id)
        )
        return [self._to_entity(model) for model in models]

    def _to_entity(self, model: EndpointModel) -> Endpoint:
        return Endpoint(
            id=model.id,
            app_id=model.app_id,
            url=model.url,
            secret=self._cipher.decrypt(model.secret_encrypted),
            event_types=list(model.event_types),
            enabled=model.enabled,
            created_at=model.created_at,
        )


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

    def get(self, message_id: UUID) -> Message:
        model = self._session.get_one(MessageModel, message_id)
        return Message(
            id=model.id,
            app_id=model.app_id,
            event_type=model.event_type,
            payload=model.payload,
            created_at=model.created_at,
        )


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

    def get_for_update(self, delivery_id: UUID) -> Delivery | None:
        # SELECT ... FOR UPDATE: otra transacción que pida la misma fila espera
        # a que esta termine, y entonces ya ve el estado nuevo.
        model = self._session.scalars(
            select(DeliveryModel).where(DeliveryModel.id == delivery_id).with_for_update()
        ).one_or_none()
        if model is None:
            return None
        return Delivery(
            id=model.id,
            message_id=model.message_id,
            endpoint_id=model.endpoint_id,
            status=DeliveryStatus(model.status),
            next_attempt_at=model.next_attempt_at,
            created_at=model.created_at,
        )

    def update(self, delivery: Delivery) -> None:
        self._session.execute(
            update(DeliveryModel)
            .where(DeliveryModel.id == delivery.id)
            .values(status=delivery.status.value, next_attempt_at=delivery.next_attempt_at)
        )


class SqlAlchemyAttemptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, attempt: Attempt) -> None:
        self._session.add(
            AttemptModel(
                id=attempt.id,
                delivery_id=attempt.delivery_id,
                number=attempt.number,
                started_at=attempt.started_at,
                duration_ms=attempt.duration_ms,
                request_headers=attempt.request_headers,
                response_status=attempt.response_status,
                response_body=attempt.response_body,
                error=attempt.error,
            )
        )
        self._session.flush()

    def count_by_delivery(self, delivery_id: UUID) -> int:
        return self._session.scalar(
            select(func.count())
            .select_from(AttemptModel)
            .where(AttemptModel.delivery_id == delivery_id)
        )
