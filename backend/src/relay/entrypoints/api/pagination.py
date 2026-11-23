"""Cursores de paginación.

Un cursor marca la posición del último elemento de una página: su created_at
y su id (el id desempata los que tienen la misma hora). Para el cliente es
opaco: solo lo copia de una respuesta a la siguiente petición, así que su
formato puede cambiar sin romper a nadie.
"""

import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

Position = tuple[datetime, UUID]


def encode_cursor(created_at: datetime, item_id: UUID) -> str:
    raw = json.dumps({"c": created_at.isoformat(), "i": str(item_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Position:
    """Lanza ValueError si el cursor no es uno de los nuestros."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        created_at = datetime.fromisoformat(data["c"])
        item_id = UUID(data["i"])
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("cursor inválido") from error
    # Sin zona horaria la comparación con la columna sería ambigua.
    if created_at.tzinfo is None:
        raise ValueError("cursor inválido")
    return created_at, item_id
