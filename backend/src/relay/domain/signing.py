"""Secretos y firma de webhooks (estándar Standard Webhooks).

Lo firmado es `"{webhook-id}.{webhook-timestamp}.{body}"` con HMAC-SHA256.
El header `webhook-signature` lleva una o varias firmas separadas por espacios,
cada una con el formato `v1,<base64>`; varias firmas permiten rotar el secreto.
"""

import base64
import hashlib
import hmac
import secrets

SECRET_PREFIX = "whsec_"
SECRET_BYTES = 32
SIGNATURE_VERSION = "v1"
TOLERANCE_SECONDS = 5 * 60


def generate_secret() -> str:
    """Genera un secreto aleatorio con el formato `whsec_<base64>`."""
    raw = secrets.token_bytes(SECRET_BYTES)
    return SECRET_PREFIX + base64.b64encode(raw).decode()


def sign(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    """Devuelve la firma `v1,<base64>` del body tal como se va a enviar."""
    key = base64.b64decode(secret.removeprefix(SECRET_PREFIX))
    to_sign = f"{msg_id}.{timestamp}.".encode() + body
    digest = hmac.new(key, to_sign, hashlib.sha256).digest()
    return f"{SIGNATURE_VERSION},{base64.b64encode(digest).decode()}"


def verify(
    secret: str,
    msg_id: str,
    timestamp: str,
    signature_header: str,
    body: bytes,
    now: int,
) -> bool:
    """Indica si el webhook es auténtico y reciente.

    `timestamp` es el valor del header tal cual llega, y `now` la hora actual en
    segundos Unix: recibirla como parámetro permite probar el tiempo en los tests.
    """
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False

    # Rechaza envíos viejos (posible repetición de un webhook capturado) o futuros.
    if abs(now - sent_at) > TOLERANCE_SECONDS:
        return False

    expected = sign(secret, msg_id, sent_at, body)
    return any(
        hmac.compare_digest(expected, candidate)
        for candidate in signature_header.split()
        if candidate.startswith(f"{SIGNATURE_VERSION},")
    )
