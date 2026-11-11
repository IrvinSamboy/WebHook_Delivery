import pytest

from fakes import make_endpoint
from relay.domain.entities import RESPONSE_BODY_LIMIT, truncate_response_body


@pytest.mark.parametrize(
    ("event_types", "enabled", "event_type", "expected"),
    [
        (["order.paid"], True, "order.paid", True),
        (["user.created", "order.paid"], True, "order.paid", True),
        (["user.created"], True, "order.paid", False),
        ([], True, "order.paid", False),
        (["order.paid"], False, "order.paid", False),
    ],
)
def test_accepts(event_types, enabled, event_type, expected):
    endpoint = make_endpoint(event_types, enabled)

    assert endpoint.accepts(event_type) is expected


def test_el_secreto_no_aparece_al_imprimir_el_endpoint():
    endpoint = make_endpoint()

    assert endpoint.secret not in repr(endpoint)


def test_un_body_corto_se_guarda_entero():
    assert truncate_response_body("ok") == "ok"


def test_un_body_largo_se_recorta_al_limite():
    body = "x" * (RESPONSE_BODY_LIMIT + 100)

    assert truncate_response_body(body) == "x" * RESPONSE_BODY_LIMIT


def test_el_recorte_no_parte_un_caracter_de_varios_bytes():
    # "ñ" ocupa 2 bytes: con un límite par y un prefijo de 1 byte,
    # el corte cae justo en mitad de una "ñ".
    body = "a" + "ñ" * RESPONSE_BODY_LIMIT

    truncated = truncate_response_body(body)

    assert len(truncated.encode()) <= RESPONSE_BODY_LIMIT
    assert truncated == "a" + "ñ" * ((RESPONSE_BODY_LIMIT - 1) // 2)
