from enum import StrEnum


class DeliveryStatus(StrEnum):
    """Estados posibles de una entrega."""

    PENDING = "pending"  # Esperando a que llegue su next_attempt_at.
    QUEUED = "queued"  # Ya está en la cola; no volver a encolar.
    SENDING = "sending"  # Un worker la tiene en la mano.
    SUCCEEDED = "succeeded"  # El receptor respondió 2xx.
    FAILED = "failed"  # Se agotaron los intentos.


# La máquina de estados: a qué estados se puede pasar desde cada uno.
#
#   PENDING ──scheduler──► QUEUED ──worker──► SENDING ──2xx──► SUCCEEDED
#      ▲                     │                  │  │
#      └──────reaper─────────┴──────────────────┘  └──último intento──► FAILED
#      ▲                                        │                         │
#      └────────────falla y quedan intentos─────┘     reintento manual ───┘──► QUEUED
ALLOWED_TRANSITIONS: dict[DeliveryStatus, frozenset[DeliveryStatus]] = {
    DeliveryStatus.PENDING: frozenset({DeliveryStatus.QUEUED}),
    DeliveryStatus.QUEUED: frozenset({DeliveryStatus.SENDING, DeliveryStatus.PENDING}),
    DeliveryStatus.SENDING: frozenset(
        {DeliveryStatus.SUCCEEDED, DeliveryStatus.FAILED, DeliveryStatus.PENDING}
    ),
    DeliveryStatus.SUCCEEDED: frozenset(),
    DeliveryStatus.FAILED: frozenset({DeliveryStatus.QUEUED}),
}
