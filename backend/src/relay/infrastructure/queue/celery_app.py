"""La app de Celery: la usan la API (para encolar) y el worker (para ejecutar).

Arranca el worker y el reloj de tareas periódicas con:
    celery -A relay.infrastructure.queue.celery_app worker
    celery -A relay.infrastructure.queue.celery_app beat

De beat debe haber un solo proceso: dos publicarían cada tarea dos veces.
"""

from typing import Any

from celery import Celery

from relay.config import get_settings

DELIVER_TASK = "relay.deliver"
SCHEDULE_TASK = "relay.schedule_due"
RECOVER_TASK = "relay.recover_stuck"

SCHEDULE_EVERY = 5.0  # segundos
RECOVER_EVERY = 60.0

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
        # Celery Beat publica estas tareas periódicas; las ejecuta el worker.
        # expires: si nadie la ejecuta antes del siguiente tick, se descarta.
        # Con los workers ocupados no se acumulan ticks viejos en la cola.
        "beat_schedule": {
            "schedule-due": {
                "task": SCHEDULE_TASK,
                "schedule": SCHEDULE_EVERY,
                "options": {"expires": SCHEDULE_EVERY},
            },
            "recover-stuck": {
                "task": RECOVER_TASK,
                "schedule": RECOVER_EVERY,
                "options": {"expires": RECOVER_EVERY},
            },
        },
    }


# Se lee la configuración la primera vez que se necesita, no al importar:
# importar este módulo no exige tener las variables de entorno.
app.add_defaults(celery_config)
