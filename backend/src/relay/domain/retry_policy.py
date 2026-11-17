"""Cuándo reintentar una entrega fallida: backoff exponencial con jitter.

Con la base de producción (30 s), las esperas tras cada fallo son
30 s, 1, 2, 4, 8, 16, 32, 64 y 128 min: unas 4 h 15 min en total.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

MAX_ATTEMPTS = 10
# Cada espera se multiplica por un valor aleatorio en este rango, para que los
# sobres que fallaron a la vez no se reintenten todos en el mismo instante.
JITTER_RANGE = (0.8, 1.2)
# Un receptor puede pedir con Retry-After que esperemos más, pero no tanto
# como para congelar el sobre.
MAX_RETRY_AFTER = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    base_seconds: float
    max_attempts: int = MAX_ATTEMPTS
    # Se puede sustituir en los tests para que el resultado sea predecible.
    jitter: Callable[[float, float], float] = field(default=random.uniform, repr=False)

    def delay_after(self, attempt: int, retry_after: timedelta | None = None) -> timedelta:
        """La espera tras el fallo del intento `attempt` (1 = el primero)."""
        backoff = self.base_seconds * 2 ** (attempt - 1) * self.jitter(*JITTER_RANGE)
        delay = timedelta(seconds=backoff)
        if retry_after is not None:
            delay = max(delay, min(retry_after, MAX_RETRY_AFTER))
        return delay
