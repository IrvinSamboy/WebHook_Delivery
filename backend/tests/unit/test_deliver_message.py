import json
from datetime import timedelta
from uuid import uuid4

import pytest

from fakes import NOW, FakeClock, FakeHttpSender, FakeUnitOfWork, make_endpoint
from relay.application.ports import HttpResult
from relay.application.use_cases.deliver_message import DeliverMessage
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import RESPONSE_BODY_LIMIT, Attempt, Delivery, Message
from relay.domain.signing import verify


def setup(status: DeliveryStatus = DeliveryStatus.PENDING, created_at=NOW):
    """Una base de datos falsa con un sobre listo para enviar."""
    endpoint = make_endpoint()
    message = Message(
        id=uuid4(),
        app_id=endpoint.app_id,
        event_type="order.paid",
        payload={"order_id": "ord_981"},
        created_at=created_at,
    )
    delivery = Delivery(
        id=uuid4(),
        message_id=message.id,
        endpoint_id=endpoint.id,
        status=status,
        next_attempt_at=NOW,
        created_at=NOW,
    )
    uow = FakeUnitOfWork(endpoints=[endpoint])
    uow.messages.add(message)
    uow.deliveries.add(delivery)
    return uow, endpoint, message, delivery


def deliver(uow: FakeUnitOfWork, delivery: Delivery, sender: FakeHttpSender) -> None:
    DeliverMessage(uow, sender, FakeClock()).execute(delivery.id)


def stored(uow: FakeUnitOfWork) -> Delivery:
    return uow.deliveries.items[0]


def test_una_respuesta_2xx_marca_la_entrega_como_exitosa():
    uow, endpoint, _, delivery = setup()
    sender = FakeHttpSender(HttpResult(status=200, body="ok", error=None, duration_ms=85))

    deliver(uow, delivery, sender)

    assert stored(uow).status is DeliveryStatus.SUCCEEDED
    [attempt] = uow.attempts.items
    assert attempt.number == 1
    assert attempt.response_status == 200
    assert attempt.response_body == "ok"
    assert attempt.duration_ms == 85
    assert attempt.started_at == NOW
    assert attempt.error is None
    assert sender.requests[0].url == endpoint.url


@pytest.mark.parametrize("status", [301, 404, 503])
def test_una_respuesta_que_no_es_2xx_marca_la_entrega_como_fallida(status):
    uow, _, _, delivery = setup()
    sender = FakeHttpSender(HttpResult(status=status, body="nope", error=None, duration_ms=10))

    deliver(uow, delivery, sender)

    assert stored(uow).status is DeliveryStatus.FAILED
    [attempt] = uow.attempts.items
    assert attempt.response_status == status
    assert attempt.response_body == "nope"


def test_sin_respuesta_se_guarda_el_motivo():
    uow, _, _, delivery = setup()
    sender = FakeHttpSender(HttpResult(status=None, body=None, error="timeout", duration_ms=15000))

    deliver(uow, delivery, sender)

    assert stored(uow).status is DeliveryStatus.FAILED
    [attempt] = uow.attempts.items
    assert attempt.error == "timeout"
    assert attempt.response_status is None
    assert attempt.response_body is None


def test_el_body_de_la_respuesta_se_guarda_recortado():
    uow, _, _, delivery = setup()
    long_body = "x" * (RESPONSE_BODY_LIMIT * 2)
    sender = FakeHttpSender(HttpResult(status=500, body=long_body, error=None, duration_ms=10))

    deliver(uow, delivery, sender)

    assert len(uow.attempts.items[0].response_body) == RESPONSE_BODY_LIMIT


def test_envia_el_sobre_del_estandar():
    uow, _, message, delivery = setup()
    sender = FakeHttpSender()

    deliver(uow, delivery, sender)

    assert json.loads(sender.requests[0].body) == {
        "type": "order.paid",
        "timestamp": "2026-01-01T12:00:00Z",
        "data": {"order_id": "ord_981"},
    }


def test_el_receptor_puede_verificar_la_firma():
    uow, endpoint, message, delivery = setup()
    sender = FakeHttpSender()

    deliver(uow, delivery, sender)

    request = sender.requests[0]
    assert request.headers["webhook-id"] == str(message.id)
    assert verify(
        endpoint.secret,
        request.headers["webhook-id"],
        request.headers["webhook-timestamp"],
        request.headers["webhook-signature"],
        request.body,
        now=int(NOW.timestamp()),
    )


def test_el_timestamp_del_header_es_la_hora_del_envio():
    # Si fuera la hora de creación, un reintento horas después superaría la
    # tolerancia de 5 minutos y el receptor lo rechazaría siempre.
    uow, _, _, delivery = setup(created_at=NOW - timedelta(hours=2))
    sender = FakeHttpSender()

    deliver(uow, delivery, sender)

    assert sender.requests[0].headers["webhook-timestamp"] == str(int(NOW.timestamp()))


def test_no_guarda_la_firma_en_el_intento():
    uow, _, _, delivery = setup()

    deliver(uow, delivery, FakeHttpSender())

    headers = uow.attempts.items[0].request_headers
    assert "webhook-id" in headers
    assert "webhook-signature" not in headers


def test_envia_fuera_de_cualquier_transaccion():
    # En el momento del POST, la transacción 1 ya hizo commit con el sobre en
    # SENDING, y la transacción 2 todavía no empezó.
    uow, _, _, delivery = setup()
    seen = {}

    def snapshot():
        seen["commits"] = uow.commits
        seen["status"] = stored(uow).status
        seen["attempts"] = len(uow.attempts.items)

    deliver(uow, delivery, FakeHttpSender(on_send=snapshot))

    assert seen == {"commits": 1, "status": DeliveryStatus.SENDING, "attempts": 0}
    assert uow.commits == 2


@pytest.mark.parametrize(
    "status",
    [DeliveryStatus.SENDING, DeliveryStatus.SUCCEEDED, DeliveryStatus.FAILED],
)
def test_no_reenvia_un_sobre_que_no_esta_listo(status):
    # Así, si la misma tarea llega dos veces, la segunda no hace nada.
    uow, _, _, delivery = setup(status)
    sender = FakeHttpSender()

    deliver(uow, delivery, sender)

    assert sender.requests == []
    assert uow.attempts.items == []
    assert stored(uow).status is status


def test_tambien_envia_un_sobre_encolado():
    uow, _, _, delivery = setup(DeliveryStatus.QUEUED)

    deliver(uow, delivery, FakeHttpSender())

    assert stored(uow).status is DeliveryStatus.SUCCEEDED


def test_un_sobre_que_no_existe_se_ignora():
    uow, *_ = setup()
    sender = FakeHttpSender()

    DeliverMessage(uow, sender, FakeClock()).execute(uuid4())

    assert sender.requests == []


def test_numera_los_intentos():
    uow, _, _, delivery = setup()
    uow.attempts.add(
        Attempt(uuid4(), delivery.id, 1, NOW, 10, {}, 503, "down", None)
    )

    deliver(uow, delivery, FakeHttpSender())

    assert [a.number for a in uow.attempts.items] == [1, 2]
