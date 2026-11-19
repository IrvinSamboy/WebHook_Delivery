"""Scheduler: encola las entregas pending cuya hora de reintento ya llegó.

Lo ejecuta Celery Beat cada pocos segundos. Primero reclama las entregas
(pending → queued) y confirma; después las encola. Mismo orden que
CreateMessage: el worker siempre encuentra el sobre ya en queued.
"""

import logging

from relay.application.ports import Clock, TaskQueue, UnitOfWork

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


class ScheduleDueDeliveries:
    def __init__(
        self, uow: UnitOfWork, clock: Clock, queue: TaskQueue, batch_size: int = BATCH_SIZE
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._queue = queue
        self._batch_size = batch_size

    def execute(self) -> int:
        """Devuelve cuántas entregas encoló."""
        total = 0
        # Por lotes, cada uno en su transacción corta. Si hay atraso se vacía
        # en una sola ejecución; un lote incompleto significa que no queda nada.
        while True:
            with self._uow as uow:
                ids = uow.deliveries.claim_due(self._clock.now(), self._batch_size)
                uow.commit()

            # Si encolar falla, las entregas quedan queued sin tarea y el
            # reaper las devuelve a pending. Se deja de reclamar: Redis no responde.
            try:
                for delivery_id in ids:
                    self._queue.enqueue_delivery(delivery_id)
            except Exception:
                logger.exception("No se pudieron encolar %d entregas reclamadas", len(ids))
                return total

            total += len(ids)
            if len(ids) < self._batch_size:
                return total
