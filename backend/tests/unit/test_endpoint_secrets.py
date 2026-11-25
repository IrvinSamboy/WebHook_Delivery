"""Rotación de secretos: qué secretos firman en cada momento."""

from datetime import timedelta

from fakes import NOW, make_endpoint
from relay.domain.entities import SECRET_GRACE_PERIOD

OLD = "whsec_viejo"
NEW = "whsec_nuevo"
NEWEST = "whsec_novisimo"


def rotated(expire_previous: bool = False):
    endpoint = make_endpoint()
    endpoint.secret = OLD
    endpoint.rotate_secret(NEW, NOW, expire_previous)
    return endpoint


def test_sin_rotar_firma_solo_con_su_secreto():
    endpoint = make_endpoint()

    assert endpoint.signing_secrets(NOW) == [endpoint.secret]


def test_el_periodo_de_gracia_es_de_24_horas():
    assert timedelta(hours=24) == SECRET_GRACE_PERIOD


def test_tras_rotar_el_secreto_anterior_caduca_en_24_horas():
    endpoint = rotated()

    assert endpoint.secret == NEW
    assert endpoint.previous_secret == OLD
    assert endpoint.previous_secret_expires_at == NOW + timedelta(hours=24)


def test_durante_la_gracia_firma_con_los_dos_y_el_nuevo_primero():
    endpoint = rotated()

    assert endpoint.signing_secrets(NOW) == [NEW, OLD]
    assert endpoint.signing_secrets(NOW + timedelta(hours=23, minutes=59)) == [NEW, OLD]


def test_al_terminar_la_gracia_firma_solo_con_el_nuevo():
    endpoint = rotated()

    # Justo en el límite ya no vale: la gracia es [rotación, rotación + 24 h).
    assert endpoint.signing_secrets(NOW + timedelta(hours=24)) == [NEW]
    assert endpoint.signing_secrets(NOW + timedelta(days=30)) == [NEW]


def test_con_expire_previous_el_anterior_deja_de_valer_ya():
    endpoint = rotated(expire_previous=True)

    assert endpoint.signing_secrets(NOW) == [NEW]
    assert endpoint.previous_secret is None
    assert endpoint.previous_secret_expires_at is None


def test_rotar_dos_veces_descarta_el_mas_viejo():
    endpoint = rotated()
    later = NOW + timedelta(hours=1)

    endpoint.rotate_secret(NEWEST, later)

    assert endpoint.signing_secrets(later) == [NEWEST, NEW]
    assert OLD not in endpoint.signing_secrets(later)
    assert endpoint.previous_secret_expires_at == later + timedelta(hours=24)


def test_expire_previous_durante_una_gracia_invalida_todo_lo_anterior():
    endpoint = rotated()

    # Primera rotación planificada; luego se descubre una filtración.
    endpoint.rotate_secret(NEWEST, NOW + timedelta(hours=1), expire_previous=True)

    assert endpoint.signing_secrets(NOW + timedelta(hours=1)) == [NEWEST]


def test_el_secreto_anterior_no_aparece_en_logs():
    endpoint = rotated()

    assert OLD not in repr(endpoint)
    assert NEW not in repr(endpoint)
