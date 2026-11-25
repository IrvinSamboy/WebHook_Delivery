from datetime import timedelta
from uuid import uuid4

import pytest

from fakes import NOW, FakeClock, FakeUnitOfWork, make_endpoint
from relay.application.errors import EndpointNotFound
from relay.application.use_cases.rotate_endpoint_secret import RotateEndpointSecret

APP_ID = uuid4()


def setup():
    endpoint = make_endpoint(app_id=APP_ID)
    return FakeUnitOfWork(endpoints=[endpoint]), endpoint


def rotate(uow, endpoint_id, app_id=APP_ID, expire_previous=False):
    return RotateEndpointSecret(uow, FakeClock()).execute(app_id, endpoint_id, expire_previous)


def test_genera_un_secreto_nuevo_y_guarda_el_anterior():
    uow, endpoint = setup()
    old_secret = endpoint.secret

    result = rotate(uow, endpoint.id)

    saved = uow.endpoints.items[0]
    assert saved.secret.startswith("whsec_")
    assert saved.secret != old_secret
    assert saved.previous_secret == old_secret
    assert saved.previous_secret_expires_at == NOW + timedelta(hours=24)
    assert result.secret == saved.secret
    assert uow.committed


def test_cada_rotacion_genera_un_secreto_distinto():
    uow, endpoint = setup()

    first = rotate(uow, endpoint.id).secret
    second = rotate(uow, endpoint.id).secret

    assert first != second


def test_con_expire_previous_no_guarda_el_anterior():
    uow, endpoint = setup()

    rotate(uow, endpoint.id, expire_previous=True)

    assert uow.endpoints.items[0].previous_secret is None


def test_no_cambia_el_resto_del_endpoint():
    uow, endpoint = setup()

    rotate(uow, endpoint.id)

    saved = uow.endpoints.items[0]
    assert (saved.url, saved.event_types, saved.enabled) == (
        endpoint.url,
        endpoint.event_types,
        endpoint.enabled,
    )


@pytest.mark.parametrize("de_otra_app", [False, True], ids=["inexistente", "de-otra-aplicacion"])
def test_un_endpoint_ajeno_o_inexistente_no_se_encuentra(de_otra_app):
    uow, endpoint = setup()
    old_secret = endpoint.secret

    with pytest.raises(EndpointNotFound):
        rotate(
            uow, endpoint.id if de_otra_app else uuid4(), app_id=uuid4() if de_otra_app else APP_ID
        )

    assert uow.endpoints.items[0].secret == old_secret
    assert uow.commits == 0
