from uuid import UUID

from celery import Celery

from relay.infrastructure.queue.celery_app import DELIVER_TASK


class CeleryTaskQueue:
    def __init__(self, app: Celery) -> None:
        self._app = app

    def enqueue_delivery(self, delivery_id: UUID) -> None:
        # Por nombre, sin importar la tarea: tasks.py importa el container, y el
        # container importa este módulo.
        self._app.send_task(DELIVER_TASK, args=[str(delivery_id)])
