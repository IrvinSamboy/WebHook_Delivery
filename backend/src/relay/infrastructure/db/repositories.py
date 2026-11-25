"""Repositorios: convierten entre entidades del dominio y modelos ORM.

Cada add() hace flush para enviar el INSERT en ese momento, dentro de la
transacción. Los modelos no declaran relationship(), así que SQLAlchemy no
ordena solo los INSERT: el orden es el mismo en que se llama a add(), y un
mensaje debe insertarse antes que sus entregas.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from relay.application.errors import DuplicateIdempotencyKey
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
                previous_secret_encrypted=self._encrypt_optional(endpoint.previous_secret),
                previous_secret_expires_at=endpoint.previous_secret_expires_at,
                event_types=endpoint.event_types,
                enabled=endpoint.enabled,
                created_at=endpoint.created_at,
            )
        )
        self._session.flush()

    def get(self, endpoint_id: UUID) -> Endpoint:
        return self._to_entity(self._session.get_one(EndpointModel, endpoint_id))

    def get_for_update(self, endpoint_id: UUID) -> Endpoint | None:
        model = self._session.scalars(
            select(EndpointModel).where(EndpointModel.id == endpoint_id).with_for_update()
        ).one_or_none()
        return None if model is None else self._to_entity(model)

    def update(self, endpoint: Endpoint) -> None:
        # El secreto no se toca aquí: cambiarlo es rotarlo, y eso tiene sus reglas.
        self._session.execute(
            update(EndpointModel)
            .where(EndpointModel.id == endpoint.id)
            .values(url=endpoint.url, event_types=endpoint.event_types, enabled=endpoint.enabled)
        )

    def update_secrets(self, endpoint: Endpoint) -> None:
        self._session.execute(
            update(EndpointModel)
            .where(EndpointModel.id == endpoint.id)
            .values(
                secret_encrypted=self._cipher.encrypt(endpoint.secret),
                previous_secret_encrypted=self._encrypt_optional(endpoint.previous_secret),
                previous_secret_expires_at=endpoint.previous_secret_expires_at,
            )
        )

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
            previous_secret=(
                None
                if model.previous_secret_encrypted is None
                else self._cipher.decrypt(model.previous_secret_encrypted)
            ),
            previous_secret_expires_at=model.previous_secret_expires_at,
        )

    def _encrypt_optional(self, secret: str | None) -> str | None:
        return None if secret is None else self._cipher.encrypt(secret)


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
                idempotency_key=message.idempotency_key,
                request_hash=message.request_hash,
            )
        )
        try:
            self._session.flush()
        except IntegrityError as error:
            # Se traduce a un error de la aplicación: el caso de uso no sabe de SQL.
            if "ux_messages_app_id_idempotency_key" in str(error.orig):
                raise DuplicateIdempotencyKey from error
            raise

    def get(self, message_id: UUID) -> Message:
        return self._to_entity(self._session.get_one(MessageModel, message_id))

    def get_by_idempotency_key(self, app_id: UUID, key: str) -> Message | None:
        model = self._session.scalars(
            select(MessageModel).where(
                MessageModel.app_id == app_id, MessageModel.idempotency_key == key
            )
        ).one_or_none()
        return None if model is None else self._to_entity(model)

    @staticmethod
    def _to_entity(model: MessageModel) -> Message:
        return Message(
            id=model.id,
            app_id=model.app_id,
            event_type=model.event_type,
            payload=model.payload,
            created_at=model.created_at,
            idempotency_key=model.idempotency_key,
            request_hash=model.request_hash,
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
                attempt_count=delivery.attempt_count,
                lease_id=delivery.lease_id,
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
            attempt_count=model.attempt_count,
            lease_id=model.lease_id,
        )

    def update(self, delivery: Delivery) -> None:
        self._session.execute(
            update(DeliveryModel)
            .where(DeliveryModel.id == delivery.id)
            .values(
                status=delivery.status.value,
                next_attempt_at=delivery.next_attempt_at,
                attempt_count=delivery.attempt_count,
                lease_id=delivery.lease_id,
                updated_at=func.now(),
            )
        )

    def claim_due(self, now: datetime, limit: int) -> list[UUID]:
        """Pasa a queued las entregas pending cuya hora ya llegó y devuelve sus ids.

        SKIP LOCKED: si otra transacción ya bloqueó una fila, se la salta en vez
        de esperarla. Dos schedulers a la vez nunca reclaman la misma entrega.

        La selección va en una CTE MATERIALIZED, que Postgres evalúa una sola
        vez. Con `WHERE id IN (subconsulta)` el planificador puede evaluarla
        varias veces y reclamar más filas que el límite (se comprobó: 165 con
        limit 100).
        """
        due = (
            select(DeliveryModel.id)
            .where(
                DeliveryModel.status == DeliveryStatus.PENDING.value,
                DeliveryModel.next_attempt_at <= now,
            )
            .order_by(DeliveryModel.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .cte("due")
            .prefix_with("MATERIALIZED")
        )
        claimed = (
            update(DeliveryModel)
            .where(DeliveryModel.id == due.c.id)
            .values(status=DeliveryStatus.QUEUED.value, updated_at=func.now())
            .returning(DeliveryModel.id)
            .execution_options(synchronize_session=False)
        )
        return list(self._session.scalars(claimed))

    def recover_stuck(self, older_than: timedelta) -> list[UUID]:
        """Devuelve a pending las entregas atascadas en queued o sending.

        Se compara con la hora de Postgres porque updated_at también la pone Postgres.
        """
        stuck = (
            update(DeliveryModel)
            .where(
                DeliveryModel.status.in_(
                    [DeliveryStatus.QUEUED.value, DeliveryStatus.SENDING.value]
                ),
                DeliveryModel.updated_at < func.now() - older_than,
            )
            .values(
                status=DeliveryStatus.PENDING.value,
                next_attempt_at=func.now(),
                # Se "reprograma la cerradura": el worker que la tenía, si sigue
                # vivo, ya no podrá decidir su estado.
                lease_id=None,
                updated_at=func.now(),
            )
            .returning(DeliveryModel.id)
            .execution_options(synchronize_session=False)
        )
        return list(self._session.scalars(stuck))


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
                trigger=attempt.trigger.value,
            )
        )
        self._session.flush()
