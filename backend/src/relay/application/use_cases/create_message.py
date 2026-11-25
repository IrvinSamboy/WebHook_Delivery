"""Recibe un evento del cliente: guarda el mensaje y una entrega por endpoint suscrito.

Idempotency-Key (opcional): el cliente no sabe si su petición llegó cuando se
corta la red, y lo correcto es reintentar. Con la misma key, el reintento
devuelve el mensaje ya creado en vez de crear otro (y enviar otro webhook).
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from relay.application.errors import DuplicateIdempotencyKey, IdempotencyKeyReused
from relay.application.ports import Clock, TaskQueue, UnitOfWork
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import Delivery, Message

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CreatedMessage:
    message: Message
    # True si la Idempotency-Key ya se había usado y se devuelve ese mensaje.
    replayed: bool = False


def request_hash(event_type: str, payload: dict[str, Any]) -> str:
    """Identifica el contenido de la petición: mismo evento y payload, mismo hash.

    sort_keys: {"a":1,"b":2} y {"b":2,"a":1} son la misma petición.
    """
    canonical = json.dumps(
        {"event_type": event_type, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class CreateMessage:
    def __init__(self, uow: UnitOfWork, clock: Clock, queue: TaskQueue) -> None:
        self._uow = uow
        self._clock = clock
        self._queue = queue

    def execute(
        self,
        app_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> CreatedMessage:
        """Lanza IdempotencyKeyReused si la key ya se usó con otra petición."""
        hash_ = None if idempotency_key is None else request_hash(event_type, payload)

        if idempotency_key is not None:
            existing = self._find(app_id, idempotency_key)
            if existing is not None:
                return self._replay(existing, hash_)

        try:
            message, deliveries = self._save(app_id, event_type, payload, idempotency_key, hash_)
        except DuplicateIdempotencyKey:
            # Dos reintentos a la vez: los dos vieron que la key no existía, y
            # el índice único dejó guardar solo a uno. Se devuelve el suyo.
            assert idempotency_key is not None
            existing = self._find(app_id, idempotency_key)
            assert existing is not None
            return self._replay(existing, hash_)

        # Se encola después del commit: así el worker siempre encuentra el sobre
        # en la base de datos. Si encolar falla, el mensaje ya está guardado y
        # sus sobres quedan queued sin tarea: el reaper los rescata. No se
        # lanza el error, porque el cliente reintentaría y el evento se duplicaría.
        try:
            for delivery in deliveries:
                self._queue.enqueue_delivery(delivery.id)
        except Exception:
            logger.exception("No se pudieron encolar las entregas del mensaje %s", message.id)

        return CreatedMessage(message)

    def _find(self, app_id: UUID, key: str) -> Message | None:
        with self._uow as uow:
            return uow.messages.get_by_idempotency_key(app_id, key)

    @staticmethod
    def _replay(existing: Message, hash_: str | None) -> CreatedMessage:
        # Misma key con otro contenido: es un error del cliente, no un reintento.
        if existing.request_hash != hash_:
            raise IdempotencyKeyReused
        return CreatedMessage(existing, replayed=True)

    def _save(
        self,
        app_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str | None,
        hash_: str | None,
    ) -> tuple[Message, list[Delivery]]:
        now = self._clock.now()
        message = Message(
            id=uuid4(),
            app_id=app_id,
            event_type=event_type,
            payload=payload,
            created_at=now,
            idempotency_key=idempotency_key,
            request_hash=hash_,
        )
        deliveries: list[Delivery] = []

        with self._uow as uow:
            uow.messages.add(message)

            for endpoint in uow.endpoints.list_by_app(app_id):
                if endpoint.accepts(event_type):
                    delivery = Delivery(
                        id=uuid4(),
                        message_id=message.id,
                        endpoint_id=endpoint.id,
                        # Se encolan justo después del commit (camino rápido).
                        status=DeliveryStatus.QUEUED,
                        next_attempt_at=now,
                        created_at=now,
                    )
                    uow.deliveries.add(delivery)
                    deliveries.append(delivery)

            uow.commit()

        return message, deliveries
