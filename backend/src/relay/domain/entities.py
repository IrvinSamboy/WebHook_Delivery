"""Entidades del dominio: solo importan la librería estándar."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from relay.domain.delivery_status import ALLOWED_TRANSITIONS, DeliveryStatus
from relay.domain.errors import InvalidTransition
from relay.domain.retry_policy import RetryPolicy


@dataclass(slots=True)
class Application:
    """Un cliente del servicio."""

    id: UUID
    name: str
    created_at: datetime


@dataclass(slots=True)
class ApiKey:
    """La credencial de una aplicación; nunca contiene la key en claro."""

    id: UUID
    app_id: UUID
    prefix: str
    key_hash: str
    created_at: datetime


# Tras rotar, el secreto anterior sigue firmando este tiempo: el cliente puede
# actualizar su receptor sin que falle ningún webhook.
SECRET_GRACE_PERIOD = timedelta(hours=24)


@dataclass(slots=True)
class Endpoint:
    """Una URL a la que una aplicación quiere que se entreguen sus eventos."""

    id: UUID
    app_id: UUID
    url: str
    secret: str = field(repr=False)  # Para que no aparezca en logs ni tracebacks.
    event_types: list[str]
    enabled: bool
    created_at: datetime
    previous_secret: str | None = field(default=None, repr=False)
    previous_secret_expires_at: datetime | None = None

    def accepts(self, event_type: str) -> bool:
        """Indica si este endpoint debe recibir un evento de ese tipo."""
        return self.enabled and event_type in self.event_types

    def rotate_secret(self, new_secret: str, now: datetime, expire_previous: bool = False) -> None:
        """Cambia el secreto. El actual pasa a ser el anterior durante el periodo de gracia.

        Solo se guarda un secreto anterior: rotar dos veces descarta el más viejo.
        Con expire_previous (el secreto se filtró) el actual deja de valer ya.
        """
        if expire_previous:
            self.previous_secret = None
            self.previous_secret_expires_at = None
        else:
            self.previous_secret = self.secret
            self.previous_secret_expires_at = now + SECRET_GRACE_PERIOD
        self.secret = new_secret

    def signing_secrets(self, now: datetime) -> list[str]:
        """Los secretos con los que hay que firmar ahora: el actual primero."""
        secrets = [self.secret]
        if (
            self.previous_secret is not None
            and self.previous_secret_expires_at is not None
            and now < self.previous_secret_expires_at
        ):
            secrets.append(self.previous_secret)
        return secrets


@dataclass(slots=True)
class Message:
    """La carta: el evento que envió el cliente."""

    id: UUID
    app_id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    # La Idempotency-Key que mandó el cliente y el hash de su petición: un
    # reintento con la misma key devuelve este mensaje en vez de crear otro.
    idempotency_key: str | None = None
    request_hash: str | None = None


@dataclass(slots=True)
class Delivery:
    """El sobre: la entrega de un mensaje a un endpoint concreto."""

    id: UUID
    message_id: UUID
    endpoint_id: UUID
    status: DeliveryStatus
    next_attempt_at: datetime
    created_at: datetime
    attempt_count: int = 0
    # El fencing token: identifica qué worker tiene el sobre ahora mismo.
    # Cada start_sending genera uno nuevo y el reaper lo borra al rescatarlo,
    # así que un worker que se quedó congelado ya no lo reconoce como suyo.
    lease_id: UUID | None = None

    def start_sending(self) -> UUID:
        """Un worker toma el sobre de la cola. Devuelve su lease: su "tarjeta"."""
        self._move_to(DeliveryStatus.SENDING)
        self.lease_id = uuid4()
        return self.lease_id

    def record_attempt(
        self,
        lease_id: UUID,
        succeeded: bool,
        now: datetime,
        policy: RetryPolicy,
        retry_after: timedelta | None = None,
    ) -> bool:
        """Cuenta el intento y, si el lease sigue vigente, decide qué pasa con el sobre.

        Un worker cuyo lease caducó (el reaper le quitó el sobre mientras estaba
        congelado) solo deja constancia: su POST ocurrió y cuenta para el máximo
        de intentos, pero el estado lo decide quien tiene el sobre ahora.

        Devuelve si el lease estaba vigente.
        """
        self.attempt_count += 1
        # Hay que comprobar las dos cosas: el estado dice que alguien lo está
        # enviando, el lease dice quién.
        if self.status is not DeliveryStatus.SENDING or self.lease_id != lease_id:
            return False

        self.lease_id = None
        if succeeded:
            self._move_to(DeliveryStatus.SUCCEEDED)
        elif self.attempt_count >= policy.max_attempts:
            self._move_to(DeliveryStatus.FAILED)
        else:
            self._move_to(DeliveryStatus.PENDING)
            self.next_attempt_at = now + policy.delay_after(self.attempt_count, retry_after)
        return True

    def retry_manually(self, now: datetime) -> None:
        """El cliente pide otro intento de un sobre fallido.

        Es un solo intento: attempt_count no se reinicia, así que si vuelve a
        fallar record_attempt lo devuelve directamente a failed.
        """
        # La tabla permite PENDING → QUEUED (el scheduler), pero a mano solo
        # se reintenta lo que ya falló.
        if self.status is not DeliveryStatus.FAILED:
            raise InvalidTransition(self.status, DeliveryStatus.QUEUED)
        self._move_to(DeliveryStatus.QUEUED)
        self.next_attempt_at = now

    def _move_to(self, target: DeliveryStatus) -> None:
        if target not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTransition(self.status, target)
        self.status = target


# Las respuestas pueden ser enormes (una página de error HTML, por ejemplo):
# se guarda solo el principio, que basta para depurar.
RESPONSE_BODY_LIMIT = 4096


def truncate_response_body(body: str) -> str:
    """Recorta el body a RESPONSE_BODY_LIMIT bytes sin partir un carácter."""
    encoded = body.encode()
    if len(encoded) <= RESPONSE_BODY_LIMIT:
        return body
    return encoded[:RESPONSE_BODY_LIMIT].decode(errors="ignore")


class AttemptTrigger(StrEnum):
    """Quién provocó el intento."""

    AUTO = "auto"  # El primer envío o un reintento automático.
    MANUAL = "manual"  # Un reintento pedido por el cliente desde la API.


@dataclass(slots=True)
class Attempt:
    """Un intento de entrega: qué se envió y qué pasó.

    Si hubo respuesta, `response_status` la describe aunque no sea 2xx.
    Si no la hubo (timeout, conexión rechazada...), `error` dice por qué.
    """

    id: UUID
    delivery_id: UUID
    number: int  # 1 para el primer intento, 2 para el primer reintento...
    started_at: datetime
    duration_ms: int
    request_headers: dict[str, str]
    response_status: int | None
    response_body: str | None
    error: str | None
    trigger: AttemptTrigger = AttemptTrigger.AUTO
