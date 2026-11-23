from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from relay import container
from relay.application.errors import EndpointNotFound
from relay.application.use_cases.register_endpoint import RegisterEndpoint
from relay.application.use_cases.rotate_endpoint_secret import RotateEndpointSecret
from relay.application.use_cases.update_endpoint import UpdateEndpoint
from relay.entrypoints.api.deps import CurrentAppId, SessionDep
from relay.entrypoints.api.schemas import (
    EndpointCreated,
    EndpointIn,
    EndpointOut,
    EndpointPatch,
    SecretRotated,
)
from relay.infrastructure.db import queries

router = APIRouter(prefix="/v1/endpoints", tags=["endpoints"])

_NOT_FOUND = "Endpoint no encontrado"


@router.post("", status_code=status.HTTP_201_CREATED)
def register_endpoint(
    body: EndpointIn,
    app_id: CurrentAppId,
    use_case: Annotated[RegisterEndpoint, Depends(container.register_endpoint)],
) -> EndpointCreated:
    endpoint = use_case.execute(app_id, str(body.url), body.event_types)
    return EndpointCreated(
        id=endpoint.id,
        url=endpoint.url,
        event_types=endpoint.event_types,
        enabled=endpoint.enabled,
        secret=endpoint.secret,
        created_at=endpoint.created_at,
    )


@router.get("")
def list_endpoints(app_id: CurrentAppId, session: SessionDep) -> list[EndpointOut]:
    return [EndpointOut(**endpoint) for endpoint in queries.list_endpoints(session, app_id)]


@router.get("/{endpoint_id}")
def get_endpoint(endpoint_id: UUID, app_id: CurrentAppId, session: SessionDep) -> EndpointOut:
    endpoint = queries.get_endpoint(session, app_id, endpoint_id)
    if endpoint is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return EndpointOut(**endpoint)


@router.patch("/{endpoint_id}")
def update_endpoint(
    endpoint_id: UUID,
    body: EndpointPatch,
    app_id: CurrentAppId,
    use_case: Annotated[UpdateEndpoint, Depends(container.update_endpoint)],
) -> EndpointOut:
    try:
        endpoint = use_case.execute(
            app_id,
            endpoint_id,
            url=None if body.url is None else str(body.url),
            event_types=body.event_types,
            enabled=body.enabled,
        )
    except EndpointNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND) from None
    return EndpointOut(
        id=endpoint.id,
        url=endpoint.url,
        event_types=endpoint.event_types,
        enabled=endpoint.enabled,
        created_at=endpoint.created_at,
        previous_secret_expires_at=endpoint.previous_secret_expires_at,
    )


@router.post("/{endpoint_id}/rotate-secret")
def rotate_secret(
    endpoint_id: UUID,
    app_id: CurrentAppId,
    use_case: Annotated[RotateEndpointSecret, Depends(container.rotate_endpoint_secret)],
    expire_previous: bool = False,
) -> SecretRotated:
    """Genera un secreto nuevo.

    El anterior sigue firmando 24 h; con `expire_previous=true` deja de valer ya.
    """
    try:
        endpoint = use_case.execute(app_id, endpoint_id, expire_previous)
    except EndpointNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND) from None
    return SecretRotated(
        id=endpoint.id,
        secret=endpoint.secret,
        previous_secret_expires_at=endpoint.previous_secret_expires_at,
    )
