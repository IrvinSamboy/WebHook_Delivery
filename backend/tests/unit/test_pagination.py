import base64
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from relay.entrypoints.api.pagination import decode_cursor, encode_cursor

WHEN = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_un_cursor_devuelve_la_misma_posicion():
    item_id = uuid4()

    assert decode_cursor(encode_cursor(WHEN, item_id)) == (WHEN, item_id)


def test_conserva_los_microsegundos():
    # Si se perdieran, el cursor apuntaría a otro sitio y se repetirían mensajes.
    created_at, _ = decode_cursor(encode_cursor(WHEN, uuid4()))

    assert created_at.microsecond == 123456


def test_es_seguro_en_una_url():
    cursor = encode_cursor(WHEN, uuid4())

    assert all(c.isalnum() or c in "-_" for c in cursor)


@pytest.mark.parametrize(
    "cursor",
    [
        pytest.param("no-es-base64!!", id="basura"),
        pytest.param(b64("no es json"), id="no-json"),
        pytest.param(b64("[1, 2]"), id="json-no-objeto"),
        pytest.param(b64('{"c": "2026-01-01T12:00:00+00:00"}'), id="sin-id"),
        pytest.param(b64('{"c": "ayer", "i": "' + str(uuid4()) + '"}'), id="fecha-invalida"),
        pytest.param(b64('{"c": "2026-01-01T12:00:00+00:00", "i": "x"}'), id="id-invalido"),
        pytest.param(
            b64('{"c": "2026-01-01T12:00:00", "i": "' + str(uuid4()) + '"}'), id="sin-zona"
        ),
        pytest.param(base64.urlsafe_b64encode(b"\xff\xfe").decode(), id="bytes-no-utf8"),
    ],
)
def test_un_cursor_que_no_es_nuestro_es_invalido(cursor):
    with pytest.raises(ValueError):
        decode_cursor(cursor)
