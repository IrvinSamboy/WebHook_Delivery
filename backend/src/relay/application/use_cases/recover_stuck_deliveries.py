"""Reaper: rescata las entregas atascadas en queued o sending.

Una entrega se atasca si su tarea se perdió: Redis falló justo al encolar, o
el worker murió a mitad de un envío. Ninguna entrega sana pasa tanto tiempo en
esos estados (el envío tiene un timeout de 15 s), así que tras STUCK_AFTER se
devuelve a pending y el scheduler la vuelve a encolar.

Puede provocar un envío duplicado (el worker murió después de que el receptor
recibiera el webhook): es la garantía at-least-once, y el receptor deduplica
con webhook-id.
"""

import logging
from datetime import timedelta

from relay.application.ports import UnitOfWork

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(minutes=5)


class RecoverStuckDeliveries:
    def __init__(self, uow: UnitOfWork, stuck_after: timedelta = STUCK_AFTER) -> None:
        self._uow = uow
        self._stuck_after = stuck_after

    def execute(self) -> int:
        """Devuelve cuántas entregas rescató."""
        with self._uow as uow:
            ids = uow.deliveries.recover_stuck(self._stuck_after)
            uow.commit()

        # Que el reaper rescate algo indica un fallo: se avisa en el log.
        if ids:
            logger.warning("Rescatadas %d entregas atascadas: %s", len(ids), ids)
        return len(ids)
