"""Entrega un sobre: lo firma, lo envía, registra el intento y decide qué sigue.

El POST ocurre entre dos transacciones cortas, nunca dentro de una: esperar
a la red con una transacción abierta retiene una conexión de la base de datos
y el bloqueo de la fila durante todo el envío (hasta 15 s).
"""

import json
from datetime import UTC
from uuid import UUID, uuid4

from relay.application.ports import Clock, HttpSender, UnitOfWork
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import Attempt, AttemptTrigger, Message, truncate_response_body
from relay.domain.retry_policy import RetryPolicy
from relay.domain.signing import sign


def build_body(message: Message) -> bytes:
    """El sobre del estándar Standard Webhooks, serializado una sola vez.

    Se firman y se envían exactamente estos bytes.
    """
    envelope = {
        "type": message.event_type,
        "timestamp": message.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "data": message.payload,
    }
    return json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode()


class DeliverMessage:
    def __init__(
        self, uow: UnitOfWork, sender: HttpSender, clock: Clock, policy: RetryPolicy
    ) -> None:
        self._uow = uow
        self._sender = sender
        self._clock = clock
        self._policy = policy

    def execute(
        self, delivery_id: UUID, trigger: AttemptTrigger = AttemptTrigger.AUTO
    ) -> None:
        # Transacción 1: reservar el sobre.
        with self._uow as uow:
            delivery = uow.deliveries.get_for_update(delivery_id)
            # Solo se envían sobres encolados. Una tarea repetida (Celery puede
            # entregar la misma dos veces) encuentra el sobre en otro estado y
            # no hace nada; un sobre pending espera su turno del backoff.
            if delivery is None or delivery.status is not DeliveryStatus.QUEUED:
                return
            endpoint = uow.endpoints.get(delivery.endpoint_id)
            message = uow.messages.get(delivery.message_id)

            delivery.start_sending()
            uow.deliveries.update(delivery)
            uow.commit()

        # Sin transacción: firmar y enviar.
        started_at = self._clock.now()
        timestamp = int(started_at.timestamp())  # La hora del envío, no la de creación.
        body = build_body(message)
        headers = {
            "content-type": "application/json",
            "webhook-id": str(message.id),  # El mismo en cada reintento.
            "webhook-timestamp": str(timestamp),
        }
        # Durante el periodo de gracia de una rotación van dos firmas separadas
        # por un espacio; el receptor acepta el webhook si cualquiera coincide.
        signature = " ".join(
            sign(secret, str(message.id), timestamp, body)
            for secret in endpoint.signing_secrets(started_at)
        )
        result = self._sender.send(
            endpoint.url, {**headers, "webhook-signature": signature}, body
        )

        # Transacción 2: registrar lo que pasó y decidir qué sigue.
        with self._uow as uow:
            uow.attempts.add(
                Attempt(
                    id=uuid4(),
                    delivery_id=delivery.id,
                    number=delivery.attempt_count + 1,
                    started_at=started_at,
                    duration_ms=result.duration_ms,
                    request_headers=headers,  # Sin la firma: no aporta nada guardarla.
                    response_status=result.status,
                    response_body=(
                        None if result.body is None else truncate_response_body(result.body)
                    ),
                    error=result.error,
                    trigger=trigger,
                )
            )
            delivery.record_attempt(
                succeeded=result.succeeded,
                now=self._clock.now(),
                policy=self._policy,
                retry_after=result.retry_after,
            )
            uow.deliveries.update(delivery)
            uow.commit()
