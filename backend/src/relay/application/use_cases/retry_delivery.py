"""Reintento manual: el cliente pide otro intento de una entrega fallida."""

import logging
from uuid import UUID

from relay.application.errors import DeliveryNotFound
from relay.application.ports import Clock, TaskQueue, UnitOfWork
from relay.domain.entities import AttemptTrigger, Delivery

logger = logging.getLogger(__name__)


class RetryDelivery:
    def __init__(self, uow: UnitOfWork, clock: Clock, queue: TaskQueue) -> None:
        self._uow = uow
        self._clock = clock
        self._queue = queue

    def execute(self, app_id: UUID, delivery_id: UUID) -> Delivery:
        """Lanza DeliveryNotFound o InvalidTransition (si no está en failed)."""
        with self._uow as uow:
            # FOR UPDATE: dos peticiones de reintento a la vez no pueden pasar
            # las dos la comprobación; la segunda ya ve el sobre en queued.
            delivery = uow.deliveries.get_for_update(delivery_id)
            # Una entrega de otra aplicación responde igual que una inexistente:
            # así no se puede averiguar qué ids existen.
            if delivery is None or uow.messages.get(delivery.message_id).app_id != app_id:
                raise DeliveryNotFound(delivery_id)

            delivery.retry_manually(self._clock.now())
            uow.deliveries.update(delivery)
            uow.commit()

        # Como en CreateMessage: si encolar falla, el reaper la rescata (aunque
        # entonces el intento se registrará como auto).
        try:
            self._queue.enqueue_delivery(delivery.id, AttemptTrigger.MANUAL)
        except Exception:
            logger.exception("No se pudo encolar el reintento manual de %s", delivery.id)

        return delivery
