from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from relay.domain.entities import RESPONSE_BODY_LIMIT
from relay.infrastructure.http_sender import USER_AGENT, Httpx2Sender, parse_retry_after

URL = "https://receptor.test/webhook"
BODY = b'{"type":"order.paid"}'


def sender_with(handler) -> Httpx2Sender:
    """Un sender real cuyo "servidor" es la función `handler`, sin red."""
    return Httpx2Sender(transport=httpx2.MockTransport(handler))


def test_envia_el_body_y_los_headers_tal_cual():
    received = []

    def handler(request):
        received.append(request)
        return httpx2.Response(200, text="ok")

    result = sender_with(handler).send(URL, {"webhook-id": "abc"}, BODY)

    [request] = received
    assert request.method == "POST"
    assert str(request.url) == URL
    assert request.content == BODY
    assert request.headers["webhook-id"] == "abc"
    assert request.headers["user-agent"] == USER_AGENT
    assert (result.status, result.body, result.error) == (200, "ok", None)
    assert result.duration_ms >= 0


def test_devuelve_las_respuestas_de_error_sin_lanzar_excepciones():
    result = sender_with(lambda request: httpx2.Response(503, text="down")).send(URL, {}, BODY)

    assert (result.status, result.body, result.error) == (503, "down", None)
    assert result.succeeded is False


def test_no_sigue_redirecciones():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx2.Response(301, headers={"location": "https://otro.test/"})

    result = sender_with(handler).send(URL, {}, BODY)

    assert result.status == 301
    assert len(calls) == 1


def test_lee_como_maximo_el_limite_de_la_respuesta():
    big = b"x" * (RESPONSE_BODY_LIMIT * 3)

    result = sender_with(lambda request: httpx2.Response(200, content=big)).send(URL, {}, BODY)

    assert result.body == "x" * RESPONSE_BODY_LIMIT


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        pytest.param(httpx2.ReadTimeout, "timeout", id="no-responde-a-tiempo"),
        pytest.param(httpx2.ConnectTimeout, "timeout", id="no-conecta-a-tiempo"),
        pytest.param(httpx2.ConnectError, "connection_error", id="conexion-rechazada"),
        pytest.param(httpx2.RemoteProtocolError, "request_error", id="respuesta-invalida"),
    ],
)
def test_convierte_los_fallos_de_red_en_un_motivo(exception, error):
    def handler(request):
        raise exception("simulado", request=request)

    result = sender_with(handler).send(URL, {}, BODY)

    assert (result.status, result.body, result.error) == (None, None, error)


def test_lee_el_retry_after_de_la_respuesta():
    def handler(request):
        return httpx2.Response(429, headers={"retry-after": "120"})

    result = sender_with(handler).send(URL, {}, BODY)

    assert result.retry_after == timedelta(seconds=120)


def test_sin_retry_after_no_hay_espera_pedida():
    result = sender_with(lambda request: httpx2.Response(503)).send(URL, {}, BODY)

    assert result.retry_after is None


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("120", timedelta(seconds=120), id="segundos"),
        pytest.param(" 30 ", timedelta(seconds=30), id="con-espacios"),
        pytest.param("Thu, 01 Jan 2026 12:05:00 GMT", timedelta(minutes=5), id="fecha-http"),
        pytest.param("Thu, 01 Jan 2026 11:00:00 GMT", timedelta(0), id="fecha-pasada"),
        pytest.param("mañana", None, id="basura"),
        pytest.param("-5", None, id="negativo"),
        pytest.param("", None, id="vacio"),
        pytest.param(None, None, id="ausente"),
    ],
)
def test_interpreta_el_header_retry_after(value, expected):
    assert parse_retry_after(value, now=NOW) == expected
