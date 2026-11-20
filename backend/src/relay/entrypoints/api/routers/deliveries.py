from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from relay import container
from relay.application.errors import DeliveryNotFound
from relay.application.use_cases.retry_delivery import RetryDelivery
from relay.domain.errors import InvalidTransition
from relay.entrypoints.api.deps import CurrentAppId
from relay.entrypoints.api.schemas import DeliveryOut

router = APIRouter(prefix="/v1/deliveries", tags=["deliveries"])


@router.post("/{delivery_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_delivery(
    delivery_id: UUID,
    app_id: CurrentAppId,
    use_case: Annotated[RetryDelivery, Depends(container.retry_delivery)],
) -> DeliveryOut:
    try:
        delivery = use_case.execute(app_id, delivery_id)
    except DeliveryNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Entrega no encontrada") from None
    except InvalidTransition as error:
        # 409: la petición es correcta, pero choca con el estado actual.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Solo se reintentan entregas fallidas; esta está en {error.current}",
        ) from None
    return DeliveryOut(
        id=delivery.id,
        endpoint_id=delivery.endpoint_id,
        status=delivery.status,
        attempt_count=delivery.attempt_count,
        next_attempt_at=delivery.next_attempt_at,
    )
