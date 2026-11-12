from uuid import uuid4

from relay import container
from relay.infrastructure.queue import tasks
from relay.infrastructure.queue.celery_app import DELIVER_TASK, celery_config
from relay.infrastructure.queue.task_queue import CeleryTaskQueue


def test_la_tarea_entrega_el_sobre_indicado(monkeypatch):
    delivered = []

    class FakeDeliverMessage:
        def execute(self, delivery_id):
            delivered.append(delivery_id)

    monkeypatch.setattr(container, "deliver_message", FakeDeliverMessage)
    delivery_id = uuid4()

    # Llamar a la tarea como función la ejecuta aquí mismo, sin worker ni Redis.
    tasks.deliver(str(delivery_id))

    assert delivered == [delivery_id]


def test_la_cola_envia_el_id_a_la_tarea_de_entrega():
    sent = []

    class FakeCelery:
        def send_task(self, name, args):
            sent.append((name, args))

    delivery_id = uuid4()

    CeleryTaskQueue(FakeCelery()).enqueue_delivery(delivery_id)

    # Un str, no un UUID: los mensajes de la cola van en JSON.
    assert sent == [(DELIVER_TASK, [str(delivery_id)])]


def test_la_cola_y_la_tarea_usan_el_mismo_nombre():
    # Si no coincidieran, las tareas se encolarían y ningún worker las ejecutaría.
    assert tasks.deliver.name == DELIVER_TASK


def test_una_tarea_interrumpida_no_se_pierde():
    config = celery_config()

    assert config["task_acks_late"] is True
    assert config["task_reject_on_worker_lost"] is True
