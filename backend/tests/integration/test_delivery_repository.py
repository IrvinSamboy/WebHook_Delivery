"""El SQL del scheduler y del reaper, contra PostgreSQL real."""

from datetime import timedelta

import pytest
from factories import NOW, add_app, add_delivery, add_endpoint, age, status_of
from sqlalchemy import event, text

from relay.infrastructure.db.repositories import SqlAlchemyDeliveryRepository


@pytest.fixture
def endpoint(session):
    app_id = add_app(session)
    return add_endpoint(session, app_id), app_id


def deliveries(session, endpoint, count, **fields):
    endpoint_id, app_id = endpoint
    ids = [add_delivery(session, endpoint_id, app_id, **fields) for _ in range(count)]
    session.commit()
    return ids


# --- claim_due (scheduler) ---


def test_solo_reclama_pending_cuya_hora_ya_llego(session, endpoint):
    [due] = deliveries(session, endpoint, 1, next_attempt_at=NOW - timedelta(seconds=1))
    [future] = deliveries(session, endpoint, 1, next_attempt_at=NOW + timedelta(seconds=1))
    others = [
        deliveries(session, endpoint, 1, status=status, next_attempt_at=NOW - timedelta(hours=1))[0]
        for status in ("queued", "sending", "succeeded", "failed")
    ]

    claimed = SqlAlchemyDeliveryRepository(session).claim_due(NOW, limit=100)
    session.commit()

    assert claimed == [due]
    assert status_of(session, due) == "queued"
    assert status_of(session, future) == "pending"
    assert [status_of(session, d) for d in others] == ["queued", "sending", "succeeded", "failed"]


def test_no_reclama_mas_que_el_limite(session, endpoint):
    # El bug que corregimos: con `WHERE id IN (subconsulta con LIMIT)` Postgres
    # reclamaba más filas que el límite (165 con limit 100). Depende del plan
    # que elija, y el plan depende del volumen y de las estadísticas: por eso
    # 1000 filas y ANALYZE, que es lo que tendría una tabla real.
    deliveries(session, endpoint, 1000, next_attempt_at=NOW - timedelta(minutes=1))
    session.execute(text("ANALYZE deliveries"))

    claimed = SqlAlchemyDeliveryRepository(session).claim_due(NOW, limit=100)
    session.commit()

    assert len(claimed) == 100
    queued = session.scalar(text("SELECT count(*) FROM deliveries WHERE status = 'queued'"))
    assert queued == 100


def test_la_seleccion_va_en_una_cte_materialized(engine, session, endpoint):
    """Protege contra un fallo que depende del plan de consulta.

    Con `WHERE id IN (subconsulta con LIMIT ... SKIP LOCKED)` Postgres puede
    evaluar la subconsulta varias veces y reclamar más que el límite. Pasó en
    la base de desarrollo (165 con limit 100), pero en una base recién creada
    elige otro plan y no se reproduce: el test anterior no basta. Una CTE
    MATERIALIZED se evalúa una sola vez con cualquier plan.
    """
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        SqlAlchemyDeliveryRepository(session).claim_due(NOW, limit=10)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    [claim] = [s for s in statements if s.lstrip().startswith("WITH")]
    assert "AS MATERIALIZED" in claim
    assert "SKIP LOCKED" in claim


def test_reclama_primero_las_que_mas_llevan_esperando(session, endpoint):
    ids = [
        deliveries(session, endpoint, 1, next_attempt_at=NOW - timedelta(minutes=minutes))[0]
        for minutes in range(10)  # ids[9] es la más antigua.
    ]

    claimed = SqlAlchemyDeliveryRepository(session).claim_due(NOW, limit=3)

    assert set(claimed) == {ids[9], ids[8], ids[7]}


def test_dos_schedulers_a_la_vez_no_reclaman_la_misma_entrega(session_factory, session, endpoint):
    ids = deliveries(session, endpoint, 10, next_attempt_at=NOW - timedelta(minutes=1))

    # Dos transacciones abiertas a la vez: la segunda se salta las filas que
    # la primera tiene bloqueadas (SKIP LOCKED) en vez de esperarlas.
    with session_factory() as first, session_factory() as second:
        # Sin SKIP LOCKED la segunda esperaría a la primera, en el mismo hilo:
        # se quedaría colgada para siempre. Con este límite, falla en 2 s.
        second.execute(text("SET lock_timeout = '2s'"))
        claimed_first = SqlAlchemyDeliveryRepository(first).claim_due(NOW, limit=6)
        claimed_second = SqlAlchemyDeliveryRepository(second).claim_due(NOW, limit=6)
        first.commit()
        second.commit()

    assert len(claimed_first) == 6
    assert len(claimed_second) == 4
    assert set(claimed_first).isdisjoint(claimed_second)
    assert set(claimed_first) | set(claimed_second) == set(ids)


def test_reclamar_renueva_updated_at(session, endpoint):
    [delivery] = deliveries(session, endpoint, 1)
    age(session, delivery, minutes=60)
    session.commit()

    SqlAlchemyDeliveryRepository(session).claim_due(NOW, limit=10)
    session.commit()

    # Si no se renovara, el reaper la rescataría en cuanto la reclaman.
    minutes = session.scalar(
        text("SELECT extract(epoch FROM now() - updated_at) / 60 FROM deliveries")
    )
    assert minutes < 1


# --- recover_stuck (reaper) ---


@pytest.mark.parametrize("status", ["queued", "sending"])
def test_rescata_las_atascadas_mas_de_lo_permitido(session, endpoint, status):
    [stuck] = deliveries(session, endpoint, 1, status=status)
    age(session, stuck, minutes=6)
    session.commit()

    rescued = SqlAlchemyDeliveryRepository(session).recover_stuck(timedelta(minutes=5))
    session.commit()

    assert rescued == [stuck]
    assert status_of(session, stuck) == "pending"
    # Lista para el siguiente tick del scheduler.
    due = session.scalar(text("SELECT next_attempt_at <= now() FROM deliveries"))
    assert due is True


def test_no_rescata_las_que_aun_estan_en_plazo(session, endpoint):
    [recent] = deliveries(session, endpoint, 1, status="sending")
    age(session, recent, minutes=4)
    session.commit()

    rescued = SqlAlchemyDeliveryRepository(session).recover_stuck(timedelta(minutes=5))

    assert rescued == []
    assert status_of(session, recent) == "sending"


@pytest.mark.parametrize("status", ["pending", "succeeded", "failed"])
def test_no_toca_otros_estados_por_viejos_que_sean(session, endpoint, status):
    [old] = deliveries(session, endpoint, 1, status=status)
    age(session, old, minutes=600)
    session.commit()

    rescued = SqlAlchemyDeliveryRepository(session).recover_stuck(timedelta(minutes=5))

    assert rescued == []
    assert status_of(session, old) == status


# --- get_for_update / update ---


def test_update_guarda_el_estado_y_renueva_updated_at(session, endpoint):
    [delivery_id] = deliveries(session, endpoint, 1, status="queued")
    age(session, delivery_id, minutes=60)
    session.commit()
    repository = SqlAlchemyDeliveryRepository(session)

    delivery = repository.get_for_update(delivery_id)
    delivery.start_sending()
    repository.update(delivery)
    session.commit()

    assert status_of(session, delivery_id) == "sending"
    minutes = session.scalar(
        text("SELECT extract(epoch FROM now() - updated_at) / 60 FROM deliveries")
    )
    assert minutes < 1


def test_get_for_update_de_una_entrega_inexistente_devuelve_none(session):
    from uuid import uuid4

    assert SqlAlchemyDeliveryRepository(session).get_for_update(uuid4()) is None
