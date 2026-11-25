"""Límite de peticiones por aplicación: un contador por minuto en Redis.

Ventana fija: la clave cambia cada minuto (ratelimit:<app>:<minuto>). INCR es
atómico, así que varios procesos de la API cuentan sobre el mismo contador sin
pisarse. Defecto conocido: justo en el cambio de minuto pueden colarse hasta
el doble del límite durante un instante; para proteger el servicio basta.

Si Redis falla se deja pasar (fail open): rechazar a todos los clientes porque
falla el contador sería peor que el abuso que intenta evitar.
"""

import logging
import math
import time
from collections.abc import Callable
from uuid import UUID

import redis

from relay.application.ports import RateLimitDecision

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60


class RedisRateLimiter:
    def __init__(
        self, client: redis.Redis, limit: int, now: Callable[[], float] = time.time
    ) -> None:
        self._client = client
        self._limit = limit
        self._now = now  # Inyectable: los tests mueven el reloj sin esperar un minuto.

    def hit(self, app_id: UUID) -> RateLimitDecision:
        now = self._now()
        window = int(now // WINDOW_SECONDS)
        reset_seconds = max(1, math.ceil(WINDOW_SECONDS - now % WINDOW_SECONDS))
        key = f"ratelimit:{app_id}:{window}"
        try:
            pipe = self._client.pipeline()
            pipe.incr(key)
            # La clave caduca sola: cada minuto usa una nueva y la vieja sobra.
            # nx: se fija en la primera petición; renovarla no cambiaría el
            # límite, solo la mantendría en memoria unos segundos más.
            pipe.expire(key, WINDOW_SECONDS, nx=True)
            count, _ = pipe.execute()
        except redis.RedisError:
            logger.warning("Rate limit sin contar: Redis no responde", exc_info=True)
            return RateLimitDecision(True, self._limit, None, reset_seconds)

        return RateLimitDecision(
            allowed=count <= self._limit,
            limit=self._limit,
            remaining=max(0, self._limit - count),
            reset_seconds=reset_seconds,
        )
