"""Secretos y firma de webhooks (estándar Standard Webhooks)."""

import base64
import secrets

SECRET_PREFIX = "whsec_"
SECRET_BYTES = 32


def generate_secret() -> str:
    """Genera un secreto aleatorio con el formato `whsec_<base64>`."""
    raw = secrets.token_bytes(SECRET_BYTES)
    return SECRET_PREFIX + base64.b64encode(raw).decode()
