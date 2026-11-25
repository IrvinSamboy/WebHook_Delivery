"""El ciclo completo de una entrega con los casos de uso reales y Postgres real.

Solo la red (FakeHttpSender) y la cola (FakeTaskQueue) son falsas.
"""

from datetime import timedelta

from fakes import NOW, FakeClock, FakeDestinationGuard, FakeHttpSender, FakeTaskQueue
from relay.application.ports import HttpResult
from relay.application.use_cases.create_application import CreateApplication
from relay.application.use_cases.create_message import CreateMessage
from relay.application.use_cases.deliver_message import DeliverMessage
from relay.application.use_cases.register_endpoint import RegisterEndpoint
from relay.application.use_cases.schedule_due_deliveries import ScheduleDueDeliveries
from relay.domain.retry_policy import RetryPolicy
from relay.infrastructure.db import queries

POLICY = RetryPolicy(base_seconds=30, jitter=lambda a, b: 1.0)
DOWN = HttpResult(status=503, body="down", error=None, duration_ms=10)
OK = HttpResult(status=204, body="", error=None, duration_ms=10)


def test_falla_se_reprograma_y_el_scheduler_la_vuelve_a_enviar(uow, session):
    app, _ = CreateApplication(uow, FakeClock()).execute("tienda")
    RegisterEndpoint(uow, FakeClock(), FakeDestinationGuard()).execute(
        app.id, "https://example.com/hook", ["order.paid"]
    )
    queue = FakeTaskQueue()
    message = CreateMessage(uow, FakeClock(), queue).execute(app.id, "order.paid", {"n": 1}).message
    [delivery_id] = queue.enqueued

    # 1.er intento: el receptor está caído.
    DeliverMessage(uow, FakeHttpSender(DOWN), FakeClock(), POLICY).execute(delivery_id)

    [delivery] = queries.get_message(session, app.id, message.id)["deliveries"]
    assert delivery["status"] == "pending"
    assert delivery["next_attempt_at"] == NOW + timedelta(seconds=30)

    # Antes de la hora el scheduler no la toca; después, la encola.
    early = FakeTaskQueue()
    assert ScheduleDueDeliveries(uow, FakeClock(NOW + timedelta(seconds=29)), early).execute() == 0
    later = FakeTaskQueue()
    assert ScheduleDueDeliveries(uow, FakeClock(NOW + timedelta(seconds=31)), later).execute() == 1
    assert later.enqueued == [delivery_id]

    # 2.º intento: ahora responde.
    sender = FakeHttpSender(OK)
    DeliverMessage(uow, sender, FakeClock(), POLICY).execute(delivery_id)

    session.expire_all()
    [delivery] = queries.get_message(session, app.id, message.id)["deliveries"]
    assert (delivery["status"], delivery["attempt_count"]) == ("succeeded", 2)
    attempts = queries.list_attempts(session, app.id, message.id)
    assert [(a["number"], a["response_status"]) for a in attempts] == [(1, 503), (2, 204)]
    # El secreto se descifró bien: la petición salió firmada.
    assert sender.requests[0].headers["webhook-signature"].startswith("v1,")
