from datetime import timedelta
from uuid import uuid4

import pytest

from fakes import NOW, FakeClock, FakeTaskQueue, FakeUnitOfWork
from relay.application.use_cases.schedule_due_deliveries import ScheduleDueDeliveries
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import Delivery


def add_delivery(
    uow: FakeUnitOfWork,
    status: DeliveryStatus = DeliveryStatus.PENDING,
    next_attempt_at=NOW,
) -> Delivery:
    delivery = Delivery(
        id=uuid4(),
        message_id=uuid4(),
        endpoint_id=uuid4(),
        status=status,
        next_attempt_at=next_attempt_at,
        created_at=NOW - timedelta(hours=1),
    )
    uow.deliveries.add(delivery)
    return delivery


def run(uow: FakeUnitOfWork, queue: FakeTaskQueue | None = None, batch_size: int = 100) -> int:
    return ScheduleDueDeliveries(uow, FakeClock(), queue or FakeTaskQueue(), batch_size).execute()


def test_encola_las_entregas_cuya_hora_ya_llego():
    uow = FakeUnitOfWork()
    justo_ahora = add_delivery(uow, next_attempt_at=NOW)
    atrasada = add_delivery(uow, next_attempt_at=NOW - timedelta(minutes=3))
    queue = FakeTaskQueue()

    count = run(uow, queue)

    assert count == 2
    assert set(queue.enqueued) == {justo_ahora.id, atrasada.id}
    assert all(d.status is DeliveryStatus.QUEUED for d in uow.deliveries.items)


def test_no_encola_las_que_aun_esperan_su_turno():
    uow = FakeUnitOfWork()
    futura = add_delivery(uow, next_attempt_at=NOW + timedelta(seconds=1))
    queue = FakeTaskQueue()

    count = run(uow, queue)

    assert count == 0
    assert queue.enqueued == []
    assert uow.deliveries.items[0].status is DeliveryStatus.PENDING
    assert futura.status is DeliveryStatus.PENDING


@pytest.mark.parametrize("status", [s for s in DeliveryStatus if s is not DeliveryStatus.PENDING])
def test_solo_reclama_entregas_pending(status):
    uow = FakeUnitOfWork()
    add_delivery(uow, status=status, next_attempt_at=NOW - timedelta(hours=1))
    queue = FakeTaskQueue()

    run(uow, queue)

    assert queue.enqueued == []
    assert uow.deliveries.items[0].status is status


def test_confirma_la_transaccion_antes_de_encolar():
    uow = FakeUnitOfWork()
    add_delivery(uow)
    commits_al_encolar = []
    queue = FakeTaskQueue(on_enqueue=lambda: commits_al_encolar.append(uow.commits))

    run(uow, queue)

    # Si encolara antes del commit, el worker podría leer el sobre todavía pending.
    assert commits_al_encolar == [1]


def test_vacia_el_atraso_en_lotes():
    uow = FakeUnitOfWork()
    for _ in range(5):
        add_delivery(uow)
    queue = FakeTaskQueue()

    count = run(uow, queue, batch_size=2)

    assert count == 5
    assert len(queue.enqueued) == 5
    assert uow.commits == 3  # Lotes de 2, 2 y 1: el lote incompleto indica el final.


def test_un_lote_completo_obliga_a_mirar_otra_vez():
    uow = FakeUnitOfWork()
    for _ in range(4):
        add_delivery(uow)

    count = run(uow, batch_size=2)

    assert count == 4
    assert uow.commits == 3  # 2, 2 y un tercer lote vacío.


def test_si_la_cola_falla_no_lanza_error_y_lo_registra(caplog):
    uow = FakeUnitOfWork()
    delivery = add_delivery(uow)
    queue = FakeTaskQueue(error=ConnectionError("Redis caído"))

    count = run(uow, queue)

    assert count == 0
    assert "No se pudieron encolar" in caplog.text
    # Queda queued sin tarea: el reaper la devolverá a pending.
    assert uow.deliveries.items[0].status is DeliveryStatus.QUEUED
    assert uow.deliveries.items[0].id == delivery.id


def test_si_la_cola_falla_deja_de_reclamar():
    uow = FakeUnitOfWork()
    for _ in range(5):
        add_delivery(uow)
    queue = FakeTaskQueue(error=ConnectionError("Redis caído"))

    run(uow, queue, batch_size=2)

    # Un solo lote reclamado: seguir solo dejaría más entregas sin tarea.
    assert uow.commits == 1
    assert [d.status for d in uow.deliveries.items].count(DeliveryStatus.PENDING) == 3
