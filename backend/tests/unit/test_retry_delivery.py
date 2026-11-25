from uuid import uuid4

import pytest

from fakes import NOW, FakeClock, FakeTaskQueue, FakeUnitOfWork
from relay.application.errors import DeliveryNotFound
from relay.application.use_cases.retry_delivery import RetryDelivery
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import AttemptTrigger, Delivery, Message
from relay.domain.errors import InvalidTransition

APP_ID = uuid4()


def setup(status: DeliveryStatus = DeliveryStatus.FAILED, app_id=APP_ID):
    message = Message(
        id=uuid4(), app_id=app_id, event_type="order.paid", payload={}, created_at=NOW
    )
    delivery = Delivery(
        id=uuid4(),
        message_id=message.id,
        endpoint_id=uuid4(),
        status=status,
        next_attempt_at=NOW,
        created_at=NOW,
        attempt_count=10,
    )
    uow = FakeUnitOfWork()
    uow.messages.add(message)
    uow.deliveries.add(delivery)
    return uow, delivery


def retry(uow, delivery_id, queue=None, app_id=APP_ID):
    return RetryDelivery(uow, FakeClock(), queue or FakeTaskQueue()).execute(app_id, delivery_id)


def test_vuelve_a_encolar_una_entrega_fallida_como_manual():
    uow, delivery = setup()
    queue = FakeTaskQueue()

    result = retry(uow, delivery.id, queue)

    assert result.status is DeliveryStatus.QUEUED
    assert uow.deliveries.items[0].status is DeliveryStatus.QUEUED
    assert uow.committed
    assert queue.enqueued == [delivery.id]
    assert queue.triggers == [AttemptTrigger.MANUAL]


def test_confirma_antes_de_encolar():
    uow, delivery = setup()
    commits_al_encolar = []
    queue = FakeTaskQueue(on_enqueue=lambda: commits_al_encolar.append(uow.commits))

    retry(uow, delivery.id, queue)

    assert commits_al_encolar == [1]


@pytest.mark.parametrize("status", [s for s in DeliveryStatus if s is not DeliveryStatus.FAILED])
def test_rechaza_las_entregas_que_no_han_fallado(status):
    uow, delivery = setup(status)
    queue = FakeTaskQueue()

    with pytest.raises(InvalidTransition):
        retry(uow, delivery.id, queue)

    assert uow.deliveries.items[0].status is status
    assert uow.commits == 0
    assert queue.enqueued == []


def test_una_entrega_inexistente_no_se_encuentra():
    uow, _ = setup()

    with pytest.raises(DeliveryNotFound):
        retry(uow, uuid4())


def test_la_entrega_de_otra_aplicacion_no_se_encuentra():
    uow, delivery = setup(app_id=uuid4())
    queue = FakeTaskQueue()

    with pytest.raises(DeliveryNotFound):
        retry(uow, delivery.id, queue)

    assert uow.deliveries.items[0].status is DeliveryStatus.FAILED
    assert queue.enqueued == []


def test_si_la_cola_falla_no_lanza_error_y_lo_registra(caplog):
    uow, delivery = setup()
    queue = FakeTaskQueue(error=ConnectionError("Redis caído"))

    result = retry(uow, delivery.id, queue)

    # Ya está guardada en queued: el reaper la rescatará.
    assert result.status is DeliveryStatus.QUEUED
    assert "No se pudo encolar el reintento manual" in caplog.text
