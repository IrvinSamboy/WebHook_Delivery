from typing import Any
from uuid import UUID, uuid4

from relay.application.ports import Clock, UnitOfWork
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import Delivery, Message


class CreateMessage:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    def execute(self, app_id: UUID, event_type: str, payload: dict[str, Any]) -> Message:
        now = self._clock.now()
        message = Message(
            id=uuid4(),
            app_id=app_id,
            event_type=event_type,
            payload=payload,
            created_at=now,
        )

        with self._uow as uow:
            uow.messages.add(message)

            for endpoint in uow.endpoints.list_by_app(app_id):
                if endpoint.accepts(event_type):
                    uow.deliveries.add(
                        Delivery(
                            id=uuid4(),
                            message_id=message.id,
                            endpoint_id=endpoint.id,
                            status=DeliveryStatus.PENDING,
                            next_attempt_at=now,
                            created_at=now,
                        )
                    )

            uow.commit()

        return message
