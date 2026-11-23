import json
from datetime import timedelta
from uuid import uuid4

import pytest

from fakes import NOW, FakeClock, FakeHttpSender, FakeUnitOfWork, make_endpoint
from relay.application.ports import HttpResult
from relay.application.use_cases.deliver_message import DeliverMessage
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import RESPONSE_BODY_LIMIT, AttemptTrigger, Delivery, Message
from relay.domain.retry_policy import RetryPolicy
from relay.domain.signing import verify

# Sin jitter, para que la hora del reintento sea exacta.
POLICY = RetryPolicy(base_seconds=30, jitter=lambda a, b: 1.0)
OK = HttpResult(status=200, body="ok", error=None, duration_ms=85)
DOWN = HttpResult(status=503, body="down", error=None, duration_ms=10)


def setup(status=DeliveryStatus.QUEUED, attempt_count=0, created_at=NOW):
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
        attempt_count=attempt_count,
    )
    uow = FakeUnitOfWork(endpoints=[endpoint])
    uow.messages.add(message)
    uow.deliveries.add(delivery)
    return uow, endpoint, message, delivery


def deliver(uow: FakeUnitOfWork, delivery: Delivery, sender: FakeHttpSender) -> None:
    DeliverMessage(uow, sender, FakeClock(), POLICY).execute(delivery.id)


def stored(uow: FakeUnitOfWork) -> Delivery:
    return uow.deliveries.items[0]


# --- El resultado decide qué sigue ---


def test_una_respuesta_2xx_marca_la_entrega_como_exitosa():
    uow, endpoint, _, delivery = setup()
    sender = FakeHttpSender(OK)

    deliver(uow, delivery, sender)

    assert stored(uow).status is DeliveryStatus.SUCCEEDED
    assert stored(uow).attempt_count == 1
    [attempt] = uow.attempts.items
    assert attempt.number == 1
    assert attempt.response_status == 200
    assert attempt.response_body == "ok"
    assert attempt.duration_ms == 85
    assert attempt.started_at == NOW
    assert attempt.error is None
    assert sender.requests[0].url == endpoint.url


@pytest.mark.parametrize("status", [301, 404, 503])
def test_una_respuesta_que_no_es_2xx_programa_un_reintento(status):
    uow, _, _, delivery = setup()
    sender = FakeHttpSender(HttpResult(status=status, body="nope", error=None, duration_ms=10))

    deliver(uow, delivery, sender)

    assert stored(uow).status is DeliveryStatus.PENDING
    assert stored(uow).next_attempt_at == NOW + timedelta(seconds=30)
    [attempt] = uow.attempts.items
    assert attempt.response_status == status
    assert attempt.response_body == "nope"


def test_sin_respuesta_se_guarda_el_motivo_y_se_reintenta():
    uow, _, _, delivery = setup()
    sender = FakeHttpSender(HttpResult(status=None, body=None, error="timeout", duration_ms=15000))

    deliver(uow, delivery, sender)

    assert stored(uow).status is DeliveryStatus.PENDING
    [attempt] = uow.attempts.items
    assert attempt.error == "timeout"
    assert attempt.response_status is None
    assert attempt.response_body is None


def test_la_espera_crece_con_cada_intento():
    # Ya falló 3 veces: tras el 4º fallo espera 30 s × 2³ = 4 minutos.
    uow, _, _, delivery = setup(attempt_count=3)

    deliver(uow, delivery, FakeHttpSender(DOWN))

    assert stored(uow).next_attempt_at == NOW + timedelta(minutes=4)
    assert uow.attempts.items[0].number == 4


def test_el_ultimo_intento_fallido_marca_la_entrega_como_fallida():
    uow, _, _, delivery = setup(attempt_count=9)

    deliver(uow, delivery, FakeHttpSender(DOWN))

    assert stored(uow).status is DeliveryStatus.FAILED
    assert stored(uow).attempt_count == 10


def test_respeta_el_retry_after_del_receptor():
    uow, _, _, delivery = setup()
    slow_down = HttpResult(
        status=429, body="", error=None, duration_ms=5, retry_after=timedelta(minutes=10)
    )

    deliver(uow, delivery, FakeHttpSender(slow_down))

    assert stored(uow).next_attempt_at == NOW + timedelta(minutes=10)


def test_el_body_de_la_respuesta_se_guarda_recortado():
    uow, _, _, delivery = setup()
    long_body = "x" * (RESPONSE_BODY_LIMIT * 2)
    sender = FakeHttpSender(HttpResult(status=500, body=long_body, error=None, duration_ms=10))

    deliver(uow, delivery, sender)

    assert len(uow.attempts.items[0].response_body) == RESPONSE_BODY_LIMIT


# --- Qué se envía ---


def test_envia_el_sobre_del_estandar():
    uow, _, _, delivery = setup()
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


# --- Transacciones y concurrencia ---


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
    [s for s in DeliveryStatus if s is not DeliveryStatus.QUEUED],
)
def test_solo_envia_sobres_encolados(status):
    # Una tarea repetida no hace nada, y un sobre pending espera su turno.
    uow, _, _, delivery = setup(status)
    sender = FakeHttpSender()

    deliver(uow, delivery, sender)

    assert sender.requests == []
    assert uow.attempts.items == []
    assert stored(uow).status is status
    assert uow.commits == 0


def test_un_sobre_que_no_existe_se_ignora():
    uow, *_ = setup()
    sender = FakeHttpSender()

    DeliverMessage(uow, sender, FakeClock(), POLICY).execute(uuid4())

    assert sender.requests == []


# --- Quién provocó el intento ---


def test_el_intento_es_automatico_por_defecto():
    uow, _, _, delivery = setup()

    deliver(uow, delivery, FakeHttpSender(OK))

    assert uow.attempts.items[0].trigger is AttemptTrigger.AUTO


def test_registra_el_intento_manual_como_manual():
    uow, _, _, delivery = setup(attempt_count=10)

    DeliverMessage(uow, FakeHttpSender(DOWN), FakeClock(), POLICY).execute(
        delivery.id, AttemptTrigger.MANUAL
    )

    [attempt] = uow.attempts.items
    assert attempt.trigger is AttemptTrigger.MANUAL
    assert attempt.number == 11
    assert stored(uow).status is DeliveryStatus.FAILED


# --- Firma durante una rotación de secreto ---


def signature_header(uow, delivery, sender) -> str:
    deliver(uow, delivery, sender)
    return sender.requests[0].headers["webhook-signature"]


def test_durante_la_gracia_el_receptor_valida_con_el_secreto_viejo_o_el_nuevo():
    uow, endpoint, message, delivery = setup()
    old_secret = endpoint.secret
    endpoint.rotate_secret("whsec_bnVldm8=", NOW)
    sender = FakeHttpSender(OK)

    header = signature_header(uow, delivery, sender)

    request = sender.requests[0]
    assert len(header.split()) == 2
    for secret in (old_secret, "whsec_bnVldm8="):
        assert verify(
            secret,
            request.headers["webhook-id"],
            request.headers["webhook-timestamp"],
            header,
            request.body,
            now=int(NOW.timestamp()),
        )


def test_pasada_la_gracia_solo_vale_el_secreto_nuevo():
    uow, endpoint, _, delivery = setup()
    old_secret = endpoint.secret
    endpoint.rotate_secret("whsec_bnVldm8=", NOW - timedelta(hours=25))
    sender = FakeHttpSender(OK)

    header = signature_header(uow, delivery, sender)

    request = sender.requests[0]
    assert len(header.split()) == 1
    args = (request.headers["webhook-id"], request.headers["webhook-timestamp"], header, request.body)
    assert verify("whsec_bnVldm8=", *args, now=int(NOW.timestamp()))
    assert not verify(old_secret, *args, now=int(NOW.timestamp()))
