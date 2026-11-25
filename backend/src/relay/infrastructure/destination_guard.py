"""Comprueba a qué IP apunta de verdad una URL antes de enviarle nada.

Se resuelve el nombre y se miran TODAS sus IP: basta una interna para
rechazarla, porque el cliente HTTP podría conectar a cualquiera de ellas.

Se usa en dos momentos:
  - al registrar o editar el endpoint, para avisar al cliente enseguida;
  - justo antes de cada envío, por el DNS rebinding: un nombre que al
    registrarlo apuntaba a una IP pública puede apuntar luego a 127.0.0.1.

Límite conocido: entre esta comprobación y la conexión, httpx vuelve a
resolver el nombre, así que queda una ventana de milisegundos. Cerrarla del
todo exige fijar la IP en la conexión o un proxy de salida dedicado.
"""

import socket
from collections.abc import Callable
from urllib.parse import urlsplit

from relay.application.errors import DestinationNotAllowed
from relay.domain.destinations import is_public_ip

Resolver = Callable[[str, int], list[str]]


def resolve_with_dns(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


class DnsDestinationGuard:
    def __init__(self, allow_private: bool, resolve: Resolver = resolve_with_dns) -> None:
        # allow_private solo para desarrollo: el receptor de prueba es interno.
        self._allow_private = allow_private
        self._resolve = resolve

    def check(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise DestinationNotAllowed(url, "URL no válida")
        if self._allow_private:
            return

        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            addresses = self._resolve(parts.hostname, port)
        except (OSError, UnicodeError):
            raise DestinationNotAllowed(url, "no se pudo resolver el host") from None
        if not addresses:
            raise DestinationNotAllowed(url, "no se pudo resolver el host")
        if not all(is_public_ip(address) for address in addresses):
            raise DestinationNotAllowed(url, "apunta a una dirección interna")
