from uuid import uuid4

import pytest

from fakes import NOW, FakeClock, FakeTaskQueue, FakeUnitOfWork, make_endpoint
from relay.application.use_cases.create_message import CreateMessage
from relay.domain.delivery_status import DeliveryStatus

APP_ID = uuid4()


def run(uow: FakeUnitOfWork, event_type: str = "order.paid", queue: FakeTaskQueue | None = None):
    use_case = CreateMessage(uow, FakeClock(), queue or FakeTaskQueue())
    return use_case.execute(APP_ID, event_type, {"order_id": "ord_981"})


def test_guarda_el_mensaje_con_sus_datos():
    uow = FakeUnitOfWork()

    message = run(uow)

    assert uow.messages.items == [message]
    assert message.app_id == APP_ID
    assert message.event_type == "order.paid"
    assert message.payload == {"order_id": "ord_981"}
    assert message.created_at == NOW


def test_crea_una_delivery_por_cada_endpoint_suscrito():
    primero = make_endpoint(app_id=APP_ID)
    segundo = make_endpoint(app_id=APP_ID)
    uow = FakeUnitOfWork(endpoints=[primero, segundo])

    run(uow)

    assert {d.endpoint_id for d in uow.deliveries.items} == {primero.id, segundo.id}


def test_la_delivery_queda_pendiente_y_lista_para_salir():
    uow = FakeUnitOfWork(endpoints=[make_endpoint(app_id=APP_ID)])

    message = run(uow)

    delivery = uow.deliveries.items[0]
    assert delivery.message_id == message.id
    assert delivery.status is DeliveryStatus.PENDING
    assert delivery.next_attempt_at == NOW


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param(make_endpoint(["user.created"], app_id=APP_ID), id="otro-evento"),
        pytest.param(make_endpoint(enabled=False, app_id=APP_ID), id="deshabilitado"),
        pytest.param(make_endpoint(), id="de-otra-aplicacion"),
    ],
)
def test_ignora_los_endpoints_que_no_deben_recibirlo(endpoint):
    uow = FakeUnitOfWork(endpoints=[endpoint])

    run(uow)

    assert uow.deliveries.items == []


def test_sin_suscriptores_el_mensaje_se_guarda_igual():
    uow = FakeUnitOfWork()

    run(uow)

    assert len(uow.messages.items) == 1
    assert uow.deliveries.items == []
    assert uow.committed is True


def test_no_hace_commit_si_falla_a_mitad():
    uow = FakeUnitOfWork(endpoints=[make_endpoint(app_id=APP_ID)])

    def falla(_delivery):
        raise RuntimeError("se cayó la conexión")

    uow.deliveries.add = falla

    with pytest.raises(RuntimeError):
        run(uow)

    assert uow.committed is False


# --- Encolado ---


def test_encola_cada_delivery_creada():
    uow = FakeUnitOfWork(endpoints=[make_endpoint(app_id=APP_ID), make_endpoint(app_id=APP_ID)])
    queue = FakeTaskQueue()

    run(uow, queue=queue)

    assert queue.enqueued == [d.id for d in uow.deliveries.items]


def test_encola_despues_del_commit():
    # Si encolara antes, el worker podría buscar el sobre antes de que exista.
    uow = FakeUnitOfWork(endpoints=[make_endpoint(app_id=APP_ID)])
    committed_when_enqueued = []
    queue = FakeTaskQueue(on_enqueue=lambda: committed_when_enqueued.append(uow.committed))

    run(uow, queue=queue)

    assert committed_when_enqueued == [True]


def test_sin_suscriptores_no_encola_nada():
    queue = FakeTaskQueue()

    run(FakeUnitOfWork(), queue=queue)

    assert queue.enqueued == []


def test_si_el_commit_falla_no_encola_nada():
    uow = FakeUnitOfWork(endpoints=[make_endpoint(app_id=APP_ID)])
    queue = FakeTaskQueue()

    def falla():
        raise RuntimeError("se cayó la base de datos")

    uow.commit = falla

    with pytest.raises(RuntimeError):
        run(uow, queue=queue)

    assert queue.enqueued == []


def test_si_encolar_falla_el_mensaje_queda_guardado(caplog):
    # El cliente recibe 202 igual: si recibiera un error, reintentaría y el
    # evento se duplicaría. Los sobres quedan pending en la base de datos.
    uow = FakeUnitOfWork(endpoints=[make_endpoint(app_id=APP_ID)])
    queue = FakeTaskQueue(error=ConnectionError("Redis no responde"))

    message = run(uow, queue=queue)

    assert uow.messages.items == [message]
    assert uow.committed is True
    assert uow.deliveries.items[0].status is DeliveryStatus.PENDING
    assert "No se pudieron encolar" in caplog.text
