from enum import StrEnum


class DeliveryStatus(StrEnum):
    """Estados posibles de una entrega.

    Las reglas de transición entre estados llegan en la Fase 3.
    """

    PENDING = "pending"  # Esperando a que le toque salir.
    QUEUED = "queued"  # Ya está en la cola; no volver a encolar.
    SENDING = "sending"  # Un worker la tiene en la mano.
    SUCCEEDED = "succeeded"  # El receptor respondió 2xx.
    FAILED = "failed"  # Se agotaron los intentos o la URL está bloqueada.
