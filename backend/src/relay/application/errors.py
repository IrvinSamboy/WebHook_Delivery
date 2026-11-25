"""Errores de los casos de uso que la API traduce a códigos HTTP."""

from uuid import UUID


class DeliveryNotFound(Exception):
    """La entrega no existe, o es de otra aplicación: para el cliente es lo mismo."""

    def __init__(self, delivery_id: UUID) -> None:
        super().__init__(f"Entrega {delivery_id} no encontrada")
        self.delivery_id = delivery_id


class EndpointNotFound(Exception):
    """El endpoint no existe, o es de otra aplicación: para el cliente es lo mismo."""

    def __init__(self, endpoint_id: UUID) -> None:
        super().__init__(f"Endpoint {endpoint_id} no encontrado")
        self.endpoint_id = endpoint_id


class DestinationNotAllowed(Exception):
    """La URL apunta a una dirección interna o no se puede resolver."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"Destino no permitido ({reason}): {url}")
        self.url = url
        self.reason = reason
