"""Errores de los casos de uso que la API traduce a códigos HTTP."""

from uuid import UUID


class DeliveryNotFound(Exception):
    """La entrega no existe, o es de otra aplicación: para el cliente es lo mismo."""

    def __init__(self, delivery_id: UUID) -> None:
        super().__init__(f"Entrega {delivery_id} no encontrada")
        self.delivery_id = delivery_id
