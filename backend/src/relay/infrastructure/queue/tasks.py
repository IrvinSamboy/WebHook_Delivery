"""Tareas de Celery: traducen un mensaje de la cola en una llamada a un caso de uso."""

from uuid import UUID

from relay import container
from relay.infrastructure.queue.celery_app import (
    DELIVER_TASK,
    RECOVER_TASK,
    SCHEDULE_TASK,
    app,
)


@app.task(name=DELIVER_TASK)
def deliver(delivery_id: str) -> None:
    container.deliver_message().execute(UUID(delivery_id))


@app.task(name=SCHEDULE_TASK)
def schedule_due() -> int:
    return container.schedule_due_deliveries().execute()


@app.task(name=RECOVER_TASK)
def recover_stuck() -> int:
    return container.recover_stuck_deliveries().execute()
