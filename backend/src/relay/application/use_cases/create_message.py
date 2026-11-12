import logging
from typing import Any
from uuid import UUID, uuid4

from relay.application.ports import Clock, TaskQueue, UnitOfWork
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import Delivery, Message

logger = logging.getLogger(__name__)


class CreateMessage:
    def __init__(self, uow: UnitOfWork, clock: Clock, queue: TaskQueue) -> None:
        self._uow = uow
        self._clock = clock
        self._queue = queue

    def execute(self, app_id: UUID, event_type: str, payload: dict[str, Any]) -> Message:
        now = self._clock.now()
        message = Message(
            id=uuid4(),
            app_id=app_id,
            event_type=event_type,
            payload=payload,
            created_at=now,
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
                        status=DeliveryStatus.PENDING,
                        next_attempt_at=now,
                        created_at=now,
                    )
                    uow.deliveries.add(delivery)
                    deliveries.append(delivery)

            uow.commit()

        # Se encola después del commit: así el worker siempre encuentra el sobre
        # en la base de datos. Si encolar falla, el mensaje ya está guardado y
        # sus sobres quedan pending; no se lanza el error, porque el cliente
        # reintentaría y el evento se duplicaría.
        try:
            for delivery in deliveries:
                self._queue.enqueue_delivery(delivery.id)
        except Exception:
            logger.exception("No se pudieron encolar las entregas del mensaje %s", message.id)

        return message
