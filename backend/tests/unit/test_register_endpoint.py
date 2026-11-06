import base64
from uuid import uuid4

from fakes import NOW, FakeClock, FakeUnitOfWork
from relay.application.use_cases.register_endpoint import RegisterEndpoint

APP_ID = uuid4()


def run(uow: FakeUnitOfWork):
    return RegisterEndpoint(uow, FakeClock()).execute(
        APP_ID, "https://example.com/webhook", ["order.paid"]
    )


def test_guarda_el_endpoint_activo_y_hace_commit():
    uow = FakeUnitOfWork()

    endpoint = run(uow)

    assert uow.endpoints.items == [endpoint]
    assert endpoint.app_id == APP_ID
    assert endpoint.url == "https://example.com/webhook"
    assert endpoint.event_types == ["order.paid"]
    assert endpoint.enabled is True
    assert endpoint.created_at == NOW
    assert uow.committed is True


def test_el_secreto_tiene_el_formato_de_standard_webhooks():
    endpoint = run(FakeUnitOfWork())

    assert endpoint.secret.startswith("whsec_")
    raw = base64.b64decode(endpoint.secret.removeprefix("whsec_"), validate=True)
    assert len(raw) == 32


def test_cada_endpoint_recibe_un_secreto_distinto():
    assert run(FakeUnitOfWork()).secret != run(FakeUnitOfWork()).secret
