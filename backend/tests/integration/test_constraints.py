"""Las restricciones de la base de datos: la última defensa si falla el código."""

from datetime import timedelta
from uuid import uuid4

import pytest
from factories import NOW, add_app, add_delivery, add_endpoint, add_message
from sqlalchemy.exc import IntegrityError

from relay.infrastructure.db.models import AttemptModel, DeliveryModel


@pytest.fixture
def ids(session):
    app_id = add_app(session)
    return app_id, add_endpoint(session, app_id)


def attempt(delivery_id, number, **fields):
    return AttemptModel(
        **{
            "id": uuid4(),
            "delivery_id": delivery_id,
            "number": number,
            "started_at": NOW,
            "duration_ms": 10,
            "request_headers": {},
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        pytest.param({"status": "perdida"}, "status_valid", id="estado-desconocido"),
        pytest.param({"attempt_count": -1}, "attempt_count_not_negative", id="contador-negativo"),
    ],
)
def test_una_entrega_invalida_se_rechaza(session, ids, fields, constraint):
    app_id, endpoint_id = ids

    with pytest.raises(IntegrityError, match=constraint):
        add_delivery(session, endpoint_id, app_id, **fields)


def test_un_mensaje_tiene_como_maximo_una_entrega_por_endpoint(session, ids):
    app_id, endpoint_id = ids
    message_id = add_message(session, app_id)
    for _ in range(2):
        session.add(
            DeliveryModel(
                id=uuid4(),
                message_id=message_id,
                endpoint_id=endpoint_id,
                status="pending",
                next_attempt_at=NOW + timedelta(seconds=1),
            )
        )

    with pytest.raises(IntegrityError):
        session.flush()


def test_dos_intentos_no_pueden_tener_el_mismo_numero(session, ids):
    delivery_id = add_delivery(session, ids[1], ids[0])
    session.add_all([attempt(delivery_id, 1), attempt(delivery_id, 1)])

    with pytest.raises(IntegrityError, match="uq_attempts_delivery_id_number"):
        session.flush()


def test_un_trigger_desconocido_se_rechaza(session, ids):
    delivery_id = add_delivery(session, ids[1], ids[0])
    session.add(attempt(delivery_id, 1, trigger="cron"))

    with pytest.raises(IntegrityError, match="trigger_valid"):
        session.flush()
