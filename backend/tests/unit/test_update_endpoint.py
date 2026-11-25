from uuid import uuid4

import pytest

from fakes import FakeDestinationGuard, FakeUnitOfWork, make_endpoint
from relay.application.errors import DestinationNotAllowed, EndpointNotFound
from relay.application.use_cases.update_endpoint import UpdateEndpoint

APP_ID = uuid4()


def setup():
    endpoint = make_endpoint(["order.paid"], app_id=APP_ID)
    return FakeUnitOfWork(endpoints=[endpoint]), endpoint


def stored(uow: FakeUnitOfWork):
    return uow.endpoints.items[0]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        pytest.param(
            {"url": "https://nueva.com/hook"}, {"url": "https://nueva.com/hook"}, id="url"
        ),
        pytest.param(
            {"event_types": ["user.created"]}, {"event_types": ["user.created"]}, id="eventos"
        ),
        pytest.param({"enabled": False}, {"enabled": False}, id="desactivar"),
    ],
)
def test_cambia_solo_lo_indicado(changes, expected):
    uow, original = setup()
    before = {"url": original.url, "event_types": original.event_types, "enabled": True}

    UpdateEndpoint(uow, FakeDestinationGuard()).execute(APP_ID, original.id, **changes)

    after = {
        "url": stored(uow).url,
        "event_types": stored(uow).event_types,
        "enabled": stored(uow).enabled,
    }
    assert after == {**before, **expected}
    assert uow.committed


def test_puede_cambiar_varios_campos_a_la_vez():
    uow, endpoint = setup()

    result = UpdateEndpoint(uow, FakeDestinationGuard()).execute(
        APP_ID, endpoint.id, url="https://nueva.com/hook", enabled=False
    )

    assert (stored(uow).url, stored(uow).enabled) == ("https://nueva.com/hook", False)
    assert result.url == "https://nueva.com/hook"


def test_no_toca_el_secreto_ni_la_fecha_de_creacion():
    uow, endpoint = setup()

    UpdateEndpoint(uow, FakeDestinationGuard()).execute(
        APP_ID, endpoint.id, url="https://nueva.com/hook"
    )

    assert stored(uow).secret == endpoint.secret
    assert stored(uow).created_at == endpoint.created_at


def test_desactivado_deja_de_aceptar_eventos():
    uow, endpoint = setup()

    UpdateEndpoint(uow, FakeDestinationGuard()).execute(APP_ID, endpoint.id, enabled=False)

    assert stored(uow).accepts("order.paid") is False


@pytest.mark.parametrize("de_otra_app", [False, True], ids=["inexistente", "de-otra-aplicacion"])
def test_un_endpoint_ajeno_o_inexistente_no_se_encuentra(de_otra_app):
    uow, endpoint = setup()
    endpoint_id = endpoint.id if de_otra_app else uuid4()
    app_id = uuid4() if de_otra_app else APP_ID

    with pytest.raises(EndpointNotFound):
        UpdateEndpoint(uow, FakeDestinationGuard()).execute(app_id, endpoint_id, enabled=False)

    assert stored(uow).enabled is True
    assert uow.commits == 0


def test_rechaza_cambiar_la_url_a_una_interna():
    uow, endpoint = setup()
    guard = FakeDestinationGuard(blocked={"http://localhost:5432/"})

    with pytest.raises(DestinationNotAllowed):
        UpdateEndpoint(uow, guard).execute(APP_ID, endpoint.id, url="http://localhost:5432/")

    assert stored(uow).url == endpoint.url
    assert uow.commits == 0


def test_si_no_cambia_la_url_no_la_comprueba():
    # Desactivar un endpoint no debe fallar porque su DNS esté caído.
    uow, endpoint = setup()
    guard = FakeDestinationGuard(blocked={endpoint.url})

    UpdateEndpoint(uow, guard).execute(APP_ID, endpoint.id, enabled=False)

    assert guard.checked == []
    assert stored(uow).enabled is False
