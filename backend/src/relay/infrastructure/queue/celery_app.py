"""La app de Celery: la usan la API (para encolar) y el worker (para ejecutar).

Arranca el worker con:
    celery -A relay.infrastructure.queue.celery_app worker
"""

from typing import Any

from celery import Celery

from relay.config import get_settings

DELIVER_TASK = "relay.deliver"

app = Celery("relay", include=["relay.infrastructure.queue.tasks"])


def celery_config() -> dict[str, Any]:
    return {
        "broker_url": get_settings().redis_url,
        # Confirma la tarea al terminarla, no al empezarla: si el worker muere
        # a mitad, Redis la vuelve a entregar. Por eso una tarea puede
        # ejecutarse dos veces, y DeliverMessage está preparado para ello.
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        # Cada proceso reserva una sola tarea; las demás quedan disponibles
        # para otros workers.
        "worker_prefetch_multiplier": 1,
        # JSON, no pickle: leer la cola nunca ejecuta código.
        "task_serializer": "json",
        "accept_content": ["json"],
        # El resultado vive en Postgres (deliveries y attempts), no en Celery.
        "task_ignore_result": True,
    }


# Se lee la configuración la primera vez que se necesita, no al importar:
# importar este módulo no exige tener las variables de entorno.
app.add_defaults(celery_config)
