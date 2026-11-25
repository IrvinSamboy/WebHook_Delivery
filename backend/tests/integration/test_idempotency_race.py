"""Idempotency-Key contra PostgreSQL: el índice único arbitra la carrera."""

import threading
import time
from uuid import uuid4

import pytest
from factories import NOW, add_app, add_message
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from fakes import FakeClock, FakeTaskQueue
from relay.application.errors import DuplicateIdempotencyKey
from relay.application.use_cases.create_message import CreateMessage, request_hash
from relay.domain.entities import Message
from relay.infrastructure.db.repositories import SqlAlchemyMessageRepository
from relay.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


def message(app_id, key="pago-7781", payload=None):
    payload = payload or {}
    return Message(
        id=uuid4(),
        app_id=app_id,
        event_type="order.paid",
        payload=payload,
        created_at=NOW,
        idempotency_key=key,
        request_hash=request_hash("order.paid", payload),
    )


def test_el_repositorio_traduce_la_key_repetida_a_un_error_de_la_aplicacion(session):
    app_id = add_app(session)
    repository = SqlAlchemyMessageRepository(session)
    repository.add(message(app_id))
    session.commit()

    with pytest.raises(DuplicateIdempotencyKey):
        repository.add(message(app_id))


def test_la_misma_key_en_otra_aplicacion_no_choca(session):
    repository = SqlAlchemyMessageRepository(session)

    repository.add(message(add_app(session)))
    repository.add(message(add_app(session)))
    session.commit()

    assert session.scalar(text("SELECT count(*) FROM messages")) == 2


def test_los_mensajes_sin_key_no_chocan_entre_si(session):
    app_id = add_app(session)
    add_message(session, app_id)
    add_message(session, app_id)
    session.commit()  # El índice es parcial: los NULL no cuentan.


def test_la_key_y_el_hash_van_juntos(session):
    app_id = add_app(session)

    with pytest.raises(IntegrityError, match="idempotency_consistent"):
        add_message(session, app_id, idempotency_key="k", request_hash=None)


def test_dos_reintentos_a_la_vez_crean_un_solo_mensaje(session, session_factory, cipher):
    """La carrera de verdad, con dos transacciones:

    A: INSERT con la key (sin commit todavía)
    B: busca la key → no la ve (A no ha confirmado) → INSERT → se queda
       ESPERANDO en el índice único, porque A podría confirmar o deshacer
    A: COMMIT → el INSERT de B falla → B relee y devuelve el mensaje de A
    """
    app_id = add_app(session)
    session.commit()
    winner = message(app_id, payload={"n": 1})
    result = {}

    first = session_factory()
    SqlAlchemyMessageRepository(first).add(winner)  # A: insertado, sin commit.

    def second_request():
        uow = SqlAlchemyUnitOfWork(session_factory, cipher)
        result["value"] = CreateMessage(uow, FakeClock(), FakeTaskQueue()).execute(
            app_id, "order.paid", {"n": 1}, "pago-7781"
        )

    thread = threading.Thread(target=second_request)
    thread.start()
    # Se espera a que B esté de verdad bloqueado en el índice antes de confirmar A.
    for _ in range(100):
        waiting = session.scalar(
            text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
        )
        session.commit()
        if waiting:
            break
        time.sleep(0.05)
    assert waiting, "la segunda petición no llegó a bloquearse"
    first.commit()
    first.close()
    thread.join(timeout=10)

    assert result["value"].replayed is True
    assert result["value"].message.id == winner.id
    assert session.scalar(text("SELECT count(*) FROM messages")) == 1


def test_dos_aplicaciones_con_la_misma_key_reciben_mensajes_distintos(session, uow):
    # Si la búsqueda no filtrara por aplicación, la segunda recibiría el id del
    # mensaje de la primera: una fuga entre clientes.
    first_app, second_app = add_app(session), add_app(session)
    session.commit()
    use_case = CreateMessage(uow, FakeClock(), FakeTaskQueue())

    first = use_case.execute(first_app, "order.paid", {}, "pago-1")
    second = use_case.execute(second_app, "order.paid", {}, "pago-1")

    assert second.replayed is False
    assert second.message.id != first.message.id
    assert second.message.app_id == second_app
