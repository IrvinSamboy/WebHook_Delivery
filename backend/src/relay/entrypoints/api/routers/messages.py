from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from relay import container
from relay.application.use_cases.create_message import CreateMessage
from relay.entrypoints.api.deps import CurrentAppId, SessionDep
from relay.entrypoints.api.schemas import MessageAccepted, MessageIn, MessageOut
from relay.infrastructure.db import queries

router = APIRouter(prefix="/v1/messages", tags=["messages"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_message(
    body: MessageIn,
    app_id: CurrentAppId,
    use_case: Annotated[CreateMessage, Depends(container.create_message)],
) -> MessageAccepted:
    message = use_case.execute(app_id, body.event_type, body.payload)
    return MessageAccepted(id=message.id)


@router.get("/{message_id}")
def get_message(message_id: UUID, app_id: CurrentAppId, session: SessionDep) -> MessageOut:
    message = queries.get_message(session, app_id, message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado")
    return MessageOut(**message)
