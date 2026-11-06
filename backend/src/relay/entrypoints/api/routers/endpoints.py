from typing import Annotated

from fastapi import APIRouter, Depends, status

from relay import container
from relay.application.use_cases.register_endpoint import RegisterEndpoint
from relay.entrypoints.api.deps import CurrentAppId
from relay.entrypoints.api.schemas import EndpointCreated, EndpointIn

router = APIRouter(prefix="/v1/endpoints", tags=["endpoints"])


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
