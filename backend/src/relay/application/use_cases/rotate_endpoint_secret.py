"""Rota el secreto de un endpoint.

Por defecto el secreto anterior sigue firmando 24 h (rotación planificada): el
cliente actualiza su receptor cuando quiera, sin que falle ningún webhook.
Con expire_previous deja de valer al instante (el secreto se filtró): algunos
webhooks fallarán hasta que el receptor tenga el nuevo, y se reintentarán.
"""

from uuid import UUID

from relay.application.errors import EndpointNotFound
from relay.application.ports import Clock, UnitOfWork
from relay.domain.entities import Endpoint
from relay.domain.signing import generate_secret


class RotateEndpointSecret:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def execute(self, app_id: UUID, endpoint_id: UUID, expire_previous: bool = False) -> Endpoint:
        with self._uow as uow:
            # FOR UPDATE: dos rotaciones a la vez no pueden partir del mismo
            # secreto; la segunda ve el resultado de la primera.
            endpoint = uow.endpoints.get_for_update(endpoint_id)
            if endpoint is None or endpoint.app_id != app_id:
                raise EndpointNotFound(endpoint_id)

            endpoint.rotate_secret(generate_secret(), self._clock.now(), expire_previous)
            uow.endpoints.update_secrets(endpoint)
            uow.commit()

        return endpoint
