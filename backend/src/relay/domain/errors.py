"""Errores del dominio: reglas de negocio que se intentaron romper."""

from relay.domain.delivery_status import DeliveryStatus


class InvalidTransition(Exception):
    def __init__(self, current: DeliveryStatus, target: DeliveryStatus) -> None:
        super().__init__(f"Una entrega no puede pasar de {current} a {target}")
        self.current = current
        self.target = target
