"""Las lecturas de la API: paginación, estadísticas y aislamiento entre aplicaciones."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import text

from factories import NOW, add_app, add_delivery, add_endpoint, add_message
from relay.infrastructure.db import queries
from relay.infrastructure.db.models import AttemptModel


def walk(session, app_id, limit, event_type=None, on_first_page=None):
    """Recorre todas las páginas como haría un cliente y devuelve los ids en orden."""
    seen, before, pages = [], None, 0
    while True:
        rows, has_more = queries.list_messages(session, app_id, limit, before, event_type)
        pages += 1
        seen += [row["id"] for row in rows]
        if on_first_page and pages == 1:
            on_first_page()
        if not has_more:
            return seen, pages
        before = (rows[-1]["created_at"], rows[-1]["id"])


def expected_order(session, app_id):
    return list(
        session.scalars(
            text("SELECT id FROM messages WHERE app_id = :a ORDER BY created_at DESC, id DESC"),
            {"a": app_id},
        )
    )


# --- list_messages ---


def test_recorre_todos_los_mensajes_sin_repetir_ni_saltar_aunque_haya_empates(session):
    app_id = add_app(session)
    # Grupos de 7 con la misma hora exacta: los cortes de página caen en mitad
    # de un empate. Un cursor solo con la hora se saltaría mensajes.
    for i in range(230):
        add_message(session, app_id, created_at=NOW + timedelta(seconds=i // 7))
    session.commit()

    seen, pages = walk(session, app_id, limit=50)

    assert pages == 5
    assert seen == expected_order(session, app_id)
    assert len(set(seen)) == 230


def test_los_mensajes_nuevos_no_desplazan_las_paginas_siguientes(session):
    app_id = add_app(session)
    for i in range(120):
        add_message(session, app_id, created_at=NOW + timedelta(seconds=i))
    session.commit()
    original = expected_order(session, app_id)

    def new_messages_arrive():
        for _ in range(5):
            add_message(session, app_id, created_at=NOW + timedelta(days=1))
        session.commit()

    seen, _ = walk(session, app_id, limit=50, on_first_page=new_messages_arrive)

    # Con OFFSET, la página 2 repetiría los 5 últimos de la página 1.
    assert seen == original


def test_si_el_total_es_multiplo_del_limite_no_hay_pagina_vacia_al_final(session):
    app_id = add_app(session)
    for i in range(100):
        add_message(session, app_id, created_at=NOW + timedelta(seconds=i))
    session.commit()

    seen, pages = walk(session, app_id, limit=50)

    assert (len(seen), pages) == (100, 2)


def test_filtra_por_tipo_de_evento(session):
    app_id = add_app(session)
    for i in range(30):
        add_message(session, app_id, event_type="user.created" if i % 3 == 0 else "order.paid")
    session.commit()

    seen, _ = walk(session, app_id, limit=4, event_type="user.created")

    assert len(seen) == len(set(seen)) == 10


def test_cada_aplicacion_ve_solo_sus_mensajes(session):
    mine, other = add_app(session), add_app(session)
    add_message(session, other)
    my_message = add_message(session, mine)
    session.commit()

    seen, _ = walk(session, mine, limit=50)

    assert seen == [my_message]
    assert queries.get_message(session, mine, my_message) is not None
    assert queries.get_message(session, other, my_message) is None


# --- endpoint_stats ---


def test_las_estadisticas_cuentan_por_estado_en_las_ultimas_24_horas(session):
    app_id = add_app(session)
    endpoint_id = add_endpoint(session, app_id)
    for status in ["succeeded"] * 6 + ["failed", "pending"]:
        add_delivery(session, endpoint_id, app_id, status=status)
    # Fuera de la ventana: no cuenta.
    add_delivery(session, endpoint_id, app_id, status="failed")
    session.execute(
        text(
            "UPDATE deliveries SET created_at = now() - interval '25 hours' "
            "WHERE id = (SELECT id FROM deliveries WHERE status = 'failed' LIMIT 1)"
        )
    )
    # De otro endpoint: no cuenta.
    add_delivery(session, add_endpoint(session, app_id), app_id, status="failed")
    session.commit()

    stats = queries.endpoint_stats(session, app_id, endpoint_id)

    assert stats["deliveries"] == {
        "pending": 1,
        "queued": 0,
        "sending": 0,
        "succeeded": 6,
        "failed": 1,
    }
    # 6 de 7 terminadas; la pending no cuenta porque aún puede salir bien.
    assert stats["success_rate"] == round(6 / 7, 4)


def test_sin_entregas_terminadas_la_tasa_es_null(session):
    app_id = add_app(session)
    endpoint_id = add_endpoint(session, app_id)
    add_delivery(session, endpoint_id, app_id, status="pending")
    session.commit()

    stats = queries.endpoint_stats(session, app_id, endpoint_id)

    assert stats["success_rate"] is None


def test_las_estadisticas_de_otra_aplicacion_no_se_encuentran(session):
    owner = add_app(session)
    endpoint_id = add_endpoint(session, owner)
    session.commit()

    assert queries.endpoint_stats(session, add_app(session), endpoint_id) is None
    assert queries.endpoint_stats(session, owner, uuid4()) is None


# --- list_attempts ---


def test_los_intentos_salen_en_orden_y_solo_para_su_aplicacion(session):
    app_id = add_app(session)
    endpoint_id = add_endpoint(session, app_id)
    delivery_id = add_delivery(session, endpoint_id, app_id)
    message_id = session.scalar(text("SELECT message_id FROM deliveries"))
    for number in (2, 1, 3):
        session.add(
            AttemptModel(
                id=uuid4(),
                delivery_id=delivery_id,
                number=number,
                started_at=NOW + timedelta(minutes=number),
                duration_ms=10,
                request_headers={"webhook-id": str(message_id)},
                response_status=500,
            )
        )
    session.commit()

    attempts = queries.list_attempts(session, app_id, message_id)

    assert [a["number"] for a in attempts] == [1, 2, 3]
    assert attempts[0]["endpoint_id"] == endpoint_id
    assert queries.list_attempts(session, add_app(session), message_id) is None


def test_un_mensaje_sin_intentos_devuelve_lista_vacia(session):
    app_id = add_app(session)
    message_id = add_message(session, app_id)
    session.commit()

    assert queries.list_attempts(session, app_id, message_id) == []
