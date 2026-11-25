"""Idempotency-Key en CreateMessage: un reintento del cliente no duplica el mensaje."""

from uuid import uuid4

import pytest

from fakes import FakeClock, FakeTaskQueue, FakeUnitOfWork, make_endpoint
from relay.application.errors import IdempotencyKeyReused
from relay.application.use_cases.create_message import CreateMessage, request_hash

APP_ID = uuid4()
PAYLOAD = {"order_id": "ord_981", "amount": 100}


def setup():
    return FakeUnitOfWork(endpoints=[make_endpoint(app_id=APP_ID)]), FakeTaskQueue()


def send(uow, queue, key="pago-7781", payload=PAYLOAD, event_type="order.paid", app_id=APP_ID):
    return CreateMessage(uow, FakeClock(), queue).execute(app_id, event_type, payload, key)


def test_la_primera_vez_crea_el_mensaje_y_guarda_la_key():
    uow, queue = setup()

    result = send(uow, queue)

    assert result.replayed is False
    assert result.message.idempotency_key == "pago-7781"
    assert result.message.request_hash == request_hash("order.paid", PAYLOAD)
    assert len(queue.enqueued) == 1


def test_un_reintento_con_la_misma_key_devuelve_el_mismo_mensaje_sin_crear_nada():
    uow, queue = setup()
    first = send(uow, queue)

    retry = send(uow, queue)

    assert retry.replayed is True
    assert retry.message.id == first.message.id
    assert len(uow.messages.items) == 1
    assert len(uow.deliveries.items) == 1
    assert len(queue.enqueued) == 1  # No se encola otra entrega: no habrá otro webhook.


def test_el_orden_de_las_claves_del_payload_no_importa():
    uow, queue = setup()
    send(uow, queue, payload={"order_id": "ord_981", "amount": 100})

    retry = send(uow, queue, payload={"amount": 100, "order_id": "ord_981"})

    assert retry.replayed is True


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"payload": {"order_id": "ord_981", "amount": 999}}, id="otro-payload"),
        pytest.param({"event_type": "order.refunded"}, id="otro-evento"),
    ],
)
def test_la_misma_key_con_otra_peticion_es_un_error(change):
    uow, queue = setup()
    send(uow, queue)

    # Probablemente el cliente reutilizó la key por error: crear o ignorar
    # en silencio ocultaría el fallo.
    with pytest.raises(IdempotencyKeyReused):
        send(uow, queue, **change)

    assert len(uow.messages.items) == 1


def test_la_key_es_por_aplicacion():
    uow, queue = setup()
    first = send(uow, queue)

    other = send(uow, queue, app_id=uuid4())

    assert other.replayed is False
    assert other.message.id != first.message.id


def test_sin_key_cada_peticion_crea_un_mensaje():
    uow, queue = setup()

    send(uow, queue, key=None)
    send(uow, queue, key=None)

    assert len(uow.messages.items) == 2
    assert all(m.request_hash is None for m in uow.messages.items)


def test_si_dos_reintentos_llegan_a_la_vez_gana_uno_y_el_otro_devuelve_su_mensaje():
    uow, queue = setup()
    winner = send(uow, FakeTaskQueue()).message
    real_lookup = uow.messages.get_by_idempotency_key
    lookups = []

    def lookup_that_misses_once(app_id, key):
        # La primera consulta "no ve" al ganador, como si los dos hubieran
        # mirado a la vez: el INSERT choca con la key y hay que releer.
        lookups.append(key)
        return None if len(lookups) == 1 else real_lookup(app_id, key)

    uow.messages.get_by_idempotency_key = lookup_that_misses_once

    result = send(uow, queue)

    assert result.replayed is True
    assert result.message.id == winner.id
    assert len(uow.messages.items) == 1
    assert queue.enqueued == []
    assert len(lookups) == 2


def test_el_hash_identifica_el_contenido():
    assert request_hash("a.b", {"x": 1}) == request_hash("a.b", {"x": 1})
    assert request_hash("a.b", {"x": 1}) != request_hash("a.b", {"x": 2})
    assert request_hash("a.b", {"x": 1}) != request_hash("a.c", {"x": 1})
    assert len(request_hash("a.b", {})) == 64  # SHA-256 en hexadecimal.
