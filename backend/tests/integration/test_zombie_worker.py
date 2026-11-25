"""El worker zombi: se congela en mitad de un envío y despierta cuando otro
worker ya tiene el sobre. Reproduce la secuencia completa con Postgres real.

    worker 1: toma el sobre (lease L1) → POST … se congela
    reaper:   >5 min en sending → pending, borra el lease
    worker 2: lo toma (lease L2) → POST → 204 → succeeded
    worker 1: despierta con timeout → su lease ya no vale
"""

import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from factories import age
from fakes import FakeClock, FakeHttpSender, FakeTaskQueue
from relay.application.ports import HttpResult
from relay.application.use_cases.create_application import CreateApplication
from relay.application.use_cases.create_message import CreateMessage
from relay.application.use_cases.deliver_message import DeliverMessage
from relay.application.use_cases.recover_stuck_deliveries import RecoverStuckDeliveries
from relay.application.use_cases.register_endpoint import RegisterEndpoint
from relay.application.use_cases.schedule_due_deliveries import ScheduleDueDeliveries
from relay.domain.retry_policy import RetryPolicy
from relay.infrastructure.db import queries
from relay.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

POLICY = RetryPolicy(base_seconds=30, jitter=lambda a, b: 1.0)
TIMEOUT = HttpResult(status=None, body=None, error="timeout", duration_ms=15000)
OK = HttpResult(status=204, body="", error=None, duration_ms=10)


def test_un_worker_congelado_no_pisa_el_trabajo_del_que_tomo_el_sobre(uow, session):
    app, _ = CreateApplication(uow, FakeClock()).execute("tienda")
    RegisterEndpoint(uow, FakeClock()).execute(app.id, "https://example.com/hook", ["order.paid"])
    queue = FakeTaskQueue()
    message = CreateMessage(uow, FakeClock(), queue).execute(app.id, "order.paid", {})
    [delivery_id] = queue.enqueued

    def while_worker_1_is_frozen():
        # El reaper ve el sobre 6 min en sending y lo rescata.
        age(session, delivery_id, minutes=6)
        session.commit()
        assert RecoverStuckDeliveries(uow).execute() == 1
        # El scheduler lo encola y worker 2 lo entrega entero. El reaper pone
        # next_attempt_at con la hora real de Postgres: el scheduler usa la real.
        later = FakeClock(datetime.now(UTC) + timedelta(seconds=1))
        assert ScheduleDueDeliveries(uow, later, FakeTaskQueue()).execute() == 1
        DeliverMessage(uow, FakeHttpSender(OK), later, POLICY).execute(delivery_id)

    # Worker 1: su POST "dura" lo que tarda todo lo anterior y acaba en timeout.
    DeliverMessage(
        uow, FakeHttpSender(TIMEOUT, on_send=while_worker_1_is_frozen), FakeClock(), POLICY
    ).execute(delivery_id)

    session.expire_all()
    [delivery] = queries.get_message(session, app.id, message.id)["deliveries"]
    # El éxito de worker 2 se mantiene: worker 1 no lo devolvió a pending.
    assert delivery["status"] == "succeeded"
    assert delivery["attempt_count"] == 2
    attempts = queries.list_attempts(session, app.id, message.id)
    # Los dos POST quedaron en el historial, con números distintos.
    assert sorted((a["number"], a["response_status"], a["error"]) for a in attempts) == [
        (1, 204, None),
        (2, None, "timeout"),
    ]
    assert session.scalar(text("SELECT lease_id FROM deliveries")) is None


def test_un_worker_congelado_no_pisa_al_que_aun_esta_enviando(
    uow, session, session_factory, cipher
):
    """El caso más delicado: worker 2 todavía espera su respuesta cuando worker 1
    despierta. El estado es sending para los dos; solo el lease dice de quién es.

        worker 1: toma (L1) → POST … ⏸
        reaper → pending;  worker 2: toma (L2) → POST … (el receptor tarda)
        worker 1: ▶ timeout → paso 3: ve sending, pero L1 ≠ L2 → solo registra
        worker 2: 204 → paso 3: L2 vigente → succeeded

    Worker 2 va en otro hilo; dos eventos fuerzan exactamente ese orden.
    """
    app, _ = CreateApplication(uow, FakeClock()).execute("tienda")
    RegisterEndpoint(uow, FakeClock()).execute(app.id, "https://example.com/hook", ["order.paid"])
    queue = FakeTaskQueue()
    message = CreateMessage(uow, FakeClock(), queue).execute(app.id, "order.paid", {})
    [delivery_id] = queue.enqueued
    worker_2_is_sending = threading.Event()
    worker_1_finished = threading.Event()
    errors = []
    # Una unidad de trabajo por worker: una sesión de SQLAlchemy no se comparte entre hilos.
    uow_1 = SqlAlchemyUnitOfWork(session_factory, cipher)
    uow_2 = SqlAlchemyUnitOfWork(session_factory, cipher)

    def worker_2():
        try:
            later = FakeClock(datetime.now(UTC) + timedelta(seconds=1))
            ScheduleDueDeliveries(uow_2, later, FakeTaskQueue()).execute()

            def slow_receiver():
                worker_2_is_sending.set()
                assert worker_1_finished.wait(timeout=10)

            DeliverMessage(uow_2, FakeHttpSender(OK, on_send=slow_receiver), later, POLICY).execute(
                delivery_id
            )
        except Exception as error:  # Para que el hilo principal vea el fallo.
            errors.append(error)

    thread = threading.Thread(target=worker_2)

    def while_worker_1_is_frozen():
        age(session, delivery_id, minutes=6)
        session.commit()
        RecoverStuckDeliveries(uow).execute()
        thread.start()
        assert worker_2_is_sending.wait(timeout=10)
        # Aquí worker 2 tiene el sobre en sending con su lease, esperando respuesta.

    DeliverMessage(
        uow_1, FakeHttpSender(TIMEOUT, on_send=while_worker_1_is_frozen), FakeClock(), POLICY
    ).execute(delivery_id)

    status_after_worker_1 = session.scalar(text("SELECT status FROM deliveries"))
    session.commit()
    worker_1_finished.set()
    thread.join(timeout=10)
    assert errors == []

    # Worker 1 terminó sin pisar el sending de worker 2.
    assert status_after_worker_1 == "sending"
    session.expire_all()
    [delivery] = queries.get_message(session, app.id, message.id)["deliveries"]
    assert (delivery["status"], delivery["attempt_count"]) == ("succeeded", 2)
    attempts = queries.list_attempts(session, app.id, message.id)
    assert sorted((a["number"], a["error"]) for a in attempts) == [(1, "timeout"), (2, None)]


def test_el_reaper_borra_el_lease_al_rescatar(uow, session):
    app, _ = CreateApplication(uow, FakeClock()).execute("tienda")
    RegisterEndpoint(uow, FakeClock()).execute(app.id, "https://example.com/hook", ["order.paid"])
    queue = FakeTaskQueue()
    CreateMessage(uow, FakeClock(), queue).execute(app.id, "order.paid", {})
    [delivery_id] = queue.enqueued
    leases = []

    def check_lease_then_freeze():
        leases.append(session.scalar(text("SELECT lease_id FROM deliveries")))
        age(session, delivery_id, minutes=6)
        session.commit()
        RecoverStuckDeliveries(uow).execute()
        leases.append(session.scalar(text("SELECT lease_id FROM deliveries")))

    DeliverMessage(
        uow, FakeHttpSender(OK, on_send=check_lease_then_freeze), FakeClock(), POLICY
    ).execute(delivery_id)

    assert leases[0] is not None  # Mientras envía, la fila tiene su lease.
    assert leases[1] is None  # El reaper lo borró.
    # Aunque su POST salió bien, el sobre ya no era suyo: queda pending.
    assert session.scalar(text("SELECT status FROM deliveries")) == "pending"
