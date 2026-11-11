import pytest

from relay.domain.signing import TOLERANCE_SECONDS, generate_secret, sign, verify

SECRET = generate_secret()
MSG_ID = "f5e68a8f-5d8d-429d-9760-4ccd46d70cdb"
TIMESTAMP = 1_762_560_000
BODY = b'{"type":"order.paid","data":{"order_id":"ord_981"}}'


def check(
    signature_header: str,
    *,
    secret: str = SECRET,
    msg_id: str = MSG_ID,
    timestamp: str = str(TIMESTAMP),
    body: bytes = BODY,
    now: int = TIMESTAMP,
) -> bool:
    """Llama a verify() con datos válidos salvo lo que cada test cambie."""
    return verify(secret, msg_id, timestamp, signature_header, body, now)


VALID = sign(SECRET, MSG_ID, TIMESTAMP, BODY)


def test_coincide_con_el_ejemplo_oficial_de_standard_webhooks():
    # Vector de prueba publicado por el estándar: garantiza que los receptores
    # que usen sus librerías oficiales podrán validar nuestras firmas.
    signature = sign(
        "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw",
        "msg_p5jXN8AQM9LWM0D4loKWxJek",
        1614265330,
        b'{"test": 2432232314}',
    )

    assert signature == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


def test_acepta_una_firma_valida():
    assert check(VALID) is True


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"body": BODY + b" "}, id="body-alterado"),
        pytest.param({"msg_id": "otro-id"}, id="otro-webhook-id"),
        pytest.param({"secret": generate_secret()}, id="otro-secreto"),
    ],
)
def test_rechaza_si_cambia_algo_de_lo_firmado(changes):
    assert check(VALID, **changes) is False


def test_rechaza_si_cambia_el_timestamp_del_header():
    # Un atacante no puede "rejuvenecer" un webhook viejo cambiando su timestamp.
    assert check(VALID, timestamp=str(TIMESTAMP + 1), now=TIMESTAMP + 1) is False


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        pytest.param(TOLERANCE_SECONDS, True, id="justo-en-el-limite"),
        pytest.param(TOLERANCE_SECONDS + 1, False, id="viejo"),
        pytest.param(-TOLERANCE_SECONDS - 1, False, id="del-futuro"),
    ],
)
def test_aplica_la_tolerancia_de_tiempo(seconds, expected):
    assert check(VALID, now=TIMESTAMP + seconds) is expected


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("", id="vacio"),
        pytest.param("basura", id="sin-version"),
        pytest.param(VALID.replace("v1,", "v2,"), id="version-desconocida"),
    ],
)
def test_rechaza_headers_mal_formados(header):
    assert check(header) is False


def test_rechaza_un_timestamp_que_no_es_un_numero():
    assert check(VALID, timestamp="ayer") is False


def test_acepta_si_alguna_de_varias_firmas_es_valida():
    # Durante una rotación de secreto se envían la firma vieja y la nueva.
    old = sign(generate_secret(), MSG_ID, TIMESTAMP, BODY)

    assert check(f"{old} {VALID}") is True
