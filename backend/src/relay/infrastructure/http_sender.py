"""El único lugar que habla HTTP con los receptores, usando httpx2."""

import time

import httpx2

from relay.application.ports import HttpResult
from relay.domain.entities import RESPONSE_BODY_LIMIT

USER_AGENT = "webhook-relay/0.1"
# 5 s para conectar; 15 s para cada una de las demás fases (enviar, esperar
# cada trozo de la respuesta...).
TIMEOUT = httpx2.Timeout(15.0, connect=5.0)


class Httpx2Sender:
    def __init__(self, transport: httpx2.BaseTransport | None = None) -> None:
        # `transport` solo se indica en los tests, para simular el servidor.
        self._client = httpx2.Client(
            timeout=TIMEOUT,
            # Seguir una redirección enviaría el webhook firmado a una URL que
            # el cliente no registró. Un 3xx cuenta como fallo.
            follow_redirects=False,
            # Ignora HTTP_PROXY y similares del entorno: los webhooks salen directos.
            trust_env=False,
            headers={"user-agent": USER_AGENT},
            transport=transport,
        )

    def send(self, url: str, headers: dict[str, str], body: bytes) -> HttpResult:
        started = time.perf_counter()
        try:
            with self._client.stream("POST", url, content=body, headers=headers) as response:
                content = _read_at_most(response, RESPONSE_BODY_LIMIT)
            return HttpResult(
                status=response.status_code,
                body=content.decode(errors="ignore"),
                error=None,
                duration_ms=_elapsed_ms(started),
            )
        except httpx2.TimeoutException:
            error = "timeout"
        except httpx2.ConnectError:
            error = "connection_error"
        except httpx2.HTTPError:
            error = "request_error"
        return HttpResult(status=None, body=None, error=error, duration_ms=_elapsed_ms(started))


def _read_at_most(response: httpx2.Response, limit: int) -> bytes:
    """Lee solo el principio de la respuesta.

    Un receptor podría responder con 1 GB; no hace falta tenerlo en memoria
    para guardar 4 KB. Al salir del `with`, el resto se descarta.
    """
    content = b""
    for chunk in response.iter_bytes():
        content += chunk
        if len(content) >= limit:
            break
    return content[:limit]


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
