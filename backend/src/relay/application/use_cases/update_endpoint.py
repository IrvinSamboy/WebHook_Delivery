"""Edita un endpoint: URL, tipos de evento o si está activo.

Solo cambia lo que se indica; None significa "dejarlo como está".

Los cambios afectan también a las entregas en curso: DeliverMessage lee el
endpoint al enviar, así que tras corregir la URL el siguiente reintento ya va
a la nueva. Desactivar deja de crear entregas para mensajes nuevos, pero las
que ya están en curso terminan sus reintentos.
"""

from uuid import UUID

from relay.application.errors import EndpointNotFound
from relay.application.ports import DestinationGuard, UnitOfWork
from relay.domain.entities import Endpoint


class UpdateEndpoint:
    def __init__(self, uow: UnitOfWork, guard: DestinationGuard) -> None:
        self._uow = uow
        self._guard = guard

    def execute(
        self,
        app_id: UUID,
        endpoint_id: UUID,
        url: str | None = None,
        event_types: list[str] | None = None,
        enabled: bool | None = None,
    ) -> Endpoint:
        """Lanza EndpointNotFound, o DestinationNotAllowed si la URL nueva es interna."""
        if url is not None:
            self._guard.check(url)  # Antes de la transacción: el DNS puede tardar.
        with self._uow as uow:
            # FOR UPDATE: dos PATCH a la vez (uno cambia la URL, otro enabled)
            # se aplican uno tras otro; sin bloqueo, el segundo pisaría al primero.
            endpoint = uow.endpoints.get_for_update(endpoint_id)
            if endpoint is None or endpoint.app_id != app_id:
                raise EndpointNotFound(endpoint_id)

            if url is not None:
                endpoint.url = url
            if event_types is not None:
                endpoint.event_types = event_types
            if enabled is not None:
                endpoint.enabled = enabled

            uow.endpoints.update(endpoint)
            uow.commit()

        return endpoint
