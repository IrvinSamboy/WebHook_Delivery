"""Entrega un sobre: lo firma, lo envía y registra el intento.

El POST ocurre entre dos transacciones cortas, nunca dentro de una: esperar
a la red con una transacción abierta retiene una conexión de la base de datos
y el bloqueo de la fila durante todo el envío (hasta 15 s).
"""

import json
from datetime import UTC
from uuid import UUID, uuid4

from relay.application.ports import Clock, HttpSender, UnitOfWork
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import Attempt, Message, truncate_response_body
from relay.domain.signing import sign

# Solo se envían sobres que nadie está enviando ni se enviaron ya. Así, si la
# misma tarea llega dos veces, la segunda no hace nada.
READY_TO_SEND = {DeliveryStatus.PENDING, DeliveryStatus.QUEUED}


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
    def __init__(self, uow: UnitOfWork, sender: HttpSender, clock: Clock) -> None:
        self._uow = uow
        self._sender = sender
        self._clock = clock

    def execute(self, delivery_id: UUID) -> None:
        # Transacción 1: reservar el sobre.
        with self._uow as uow:
            delivery = uow.deliveries.get_for_update(delivery_id)
            if delivery is None or delivery.status not in READY_TO_SEND:
                return
            endpoint = uow.endpoints.get(delivery.endpoint_id)
            message = uow.messages.get(delivery.message_id)
            number = uow.attempts.count_by_delivery(delivery.id) + 1

            delivery.status = DeliveryStatus.SENDING
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
        signature = sign(endpoint.secret, str(message.id), timestamp, body)
        result = self._sender.send(
            endpoint.url, {**headers, "webhook-signature": signature}, body
        )

        # Transacción 2: registrar lo que pasó.
        with self._uow as uow:
            uow.attempts.add(
                Attempt(
                    id=uuid4(),
                    delivery_id=delivery.id,
                    number=number,
                    started_at=started_at,
                    duration_ms=result.duration_ms,
                    request_headers=headers,  # Sin la firma: no aporta nada guardarla.
                    response_status=result.status,
                    response_body=(
                        None if result.body is None else truncate_response_body(result.body)
                    ),
                    error=result.error,
                )
            )
            delivery.status = (
                DeliveryStatus.SUCCEEDED if result.succeeded else DeliveryStatus.FAILED
            )
            uow.deliveries.update(delivery)
            uow.commit()
