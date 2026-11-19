import logging
from datetime import timedelta
from uuid import uuid4

import pytest

from fakes import NOW, FakeUnitOfWork
from relay.application.use_cases.recover_stuck_deliveries import RecoverStuckDeliveries
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import Delivery


def add_delivery(uow: FakeUnitOfWork, status: DeliveryStatus, stuck: bool) -> Delivery:
    delivery = Delivery(
        id=uuid4(),
        message_id=uuid4(),
        endpoint_id=uuid4(),
        status=status,
        next_attempt_at=NOW,
        created_at=NOW,
    )
    uow.deliveries.add(delivery)
    if stuck:
        uow.deliveries.stuck.add(delivery.id)
    return delivery


@pytest.mark.parametrize("status", [DeliveryStatus.QUEUED, DeliveryStatus.SENDING])
def test_devuelve_a_pending_las_entregas_atascadas(status):
    uow = FakeUnitOfWork()
    add_delivery(uow, status, stuck=True)

    count = RecoverStuckDeliveries(uow).execute()

    assert count == 1
    assert uow.deliveries.items[0].status is DeliveryStatus.PENDING
    assert uow.committed


def test_no_toca_las_que_siguen_en_marcha():
    uow = FakeUnitOfWork()
    add_delivery(uow, DeliveryStatus.SENDING, stuck=False)

    count = RecoverStuckDeliveries(uow).execute()

    assert count == 0
    assert uow.deliveries.items[0].status is DeliveryStatus.SENDING


def test_considera_atascada_una_entrega_tras_cinco_minutos():
    uow = FakeUnitOfWork()

    RecoverStuckDeliveries(uow).execute()

    # Muy por encima del timeout del envío (15 s): una entrega sana nunca tarda tanto.
    assert uow.deliveries.recover_calls == [timedelta(minutes=5)]


def test_avisa_en_el_log_cuando_rescata_algo(caplog):
    uow = FakeUnitOfWork()
    delivery = add_delivery(uow, DeliveryStatus.QUEUED, stuck=True)

    with caplog.at_level(logging.WARNING):
        RecoverStuckDeliveries(uow).execute()

    assert "Rescatadas 1 entregas" in caplog.text
    assert str(delivery.id) in caplog.text


def test_no_escribe_nada_en_el_log_si_no_hay_atascadas(caplog):
    uow = FakeUnitOfWork()

    with caplog.at_level(logging.WARNING):
        RecoverStuckDeliveries(uow).execute()

    assert caplog.text == ""
