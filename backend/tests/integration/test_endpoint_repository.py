"""Los secretos se guardan cifrados y solo se cambian al rotar."""

from datetime import timedelta
from uuid import uuid4

import pytest
from factories import NOW, add_app, add_endpoint
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from relay.domain.entities import Endpoint
from relay.infrastructure.db.repositories import SqlAlchemyEndpointRepository


@pytest.fixture
def repository(session, cipher):
    return SqlAlchemyEndpointRepository(session, cipher)


@pytest.fixture
def endpoint(session, repository):
    endpoint = Endpoint(
        id=uuid4(),
        app_id=add_app(session),
        url="https://example.com/hook",
        secret="whsec_c2VjcmV0bw==",
        event_types=["order.paid"],
        enabled=True,
        created_at=NOW,
    )
    repository.add(endpoint)
    session.commit()
    return endpoint


def raw(session, column):
    return session.scalar(text(f"SELECT {column} FROM endpoints"))


def test_el_secreto_se_guarda_cifrado_y_se_lee_en_claro(session, repository, endpoint):
    assert raw(session, "secret_encrypted") != endpoint.secret
    assert endpoint.secret not in raw(session, "secret_encrypted")
    assert repository.get(endpoint.id).secret == endpoint.secret


def test_rotar_guarda_los_dos_secretos_cifrados(session, repository, endpoint):
    old_secret = endpoint.secret
    endpoint.rotate_secret("whsec_bnVldm8=", NOW)

    repository.update_secrets(endpoint)
    session.commit()

    assert old_secret not in raw(session, "previous_secret_encrypted")
    loaded = repository.get(endpoint.id)
    assert (loaded.secret, loaded.previous_secret) == ("whsec_bnVldm8=", old_secret)
    assert loaded.previous_secret_expires_at == NOW + timedelta(hours=24)


def test_rotar_sin_gracia_deja_el_anterior_vacio(session, repository, endpoint):
    endpoint.rotate_secret("whsec_bnVldm8=", NOW, expire_previous=True)

    repository.update_secrets(endpoint)
    session.commit()

    loaded = repository.get(endpoint.id)
    assert (loaded.previous_secret, loaded.previous_secret_expires_at) == (None, None)


def test_update_no_toca_los_secretos(session, repository, endpoint):
    loaded = repository.get_for_update(endpoint.id)
    loaded.url = "https://nueva.com/hook"
    loaded.enabled = False
    loaded.secret = "whsec_cGlzYWRv"  # Aunque la entidad cambie, update no lo guarda.

    repository.update(loaded)
    session.commit()

    saved = repository.get(endpoint.id)
    assert (saved.url, saved.enabled) == ("https://nueva.com/hook", False)
    assert saved.secret == endpoint.secret


def test_el_secreto_anterior_y_su_caducidad_van_juntos(session):
    app_id = add_app(session)

    with pytest.raises(IntegrityError, match="previous_secret_consistent"):
        add_endpoint(
            session, app_id, previous_secret_encrypted="x", previous_secret_expires_at=None
        )
