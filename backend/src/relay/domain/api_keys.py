"""Generación y verificación de API keys.

Formato: `whr_<prefijo>.<secreto>`. El prefijo es público y sirve para encontrar
la key en la base de datos; de la key completa solo se guarda el hash.

SHA-256 basta porque la key es larga y aleatoria: no se puede adivinar probando
valores, a diferencia de una contraseña elegida por una persona, y verificarla
en cada petición sigue siendo rápido.
"""

import hashlib
import hmac
import secrets

_SEPARATOR = "."


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Devuelve (key completa, prefijo)."""
    prefix = f"whr_{secrets.token_hex(6)}"
    return f"{prefix}{_SEPARATOR}{secrets.token_urlsafe(32)}", prefix


def prefix_of(api_key: str) -> str:
    return api_key.partition(_SEPARATOR)[0]


def verify_api_key(api_key: str, key_hash: str) -> bool:
    # compare_digest tarda lo mismo aunque difieran pronto: no da pistas por tiempo.
    return hmac.compare_digest(hash_api_key(api_key), key_hash)
