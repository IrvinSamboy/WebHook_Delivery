from uuid import uuid4

import pytest

from fakes import NOW, FakeClock, FakeUnitOfWork, make_endpoint
from relay.application.use_cases.create_message import CreateMessage
from relay.domain.delivery_status import DeliveryStatus

APP_ID = uuid4()


def run(uow: FakeUnitOfWork, event_type: str = "order.paid"):
    return CreateMessage(uow, FakeClock()).execute(APP_ID, event_type, {"order_id": "ord_981"})


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
