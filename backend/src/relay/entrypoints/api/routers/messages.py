from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from relay import container
from relay.application.errors import IdempotencyKeyReused
from relay.application.use_cases.create_message import CreateMessage
from relay.entrypoints.api.deps import CurrentAppId, SessionDep, enforce_rate_limit
from relay.entrypoints.api.pagination import decode_cursor, encode_cursor
from relay.entrypoints.api.schemas import (
    AttemptOut,
    EventType,
    MessageAccepted,
    MessageIn,
    MessageOut,
    MessagePage,
    MessageSummary,
)
from relay.infrastructure.db import queries

router = APIRouter(prefix="/v1/messages", tags=["messages"])


# Caracteres ASCII visibles: lo habitual es un UUID o un id de la operación del cliente.
IdempotencyKey = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=1, max_length=255, pattern=r"^[\x21-\x7E]+$"),
]


# Solo crear mensajes tiene límite: es lo que genera trabajo (filas, tareas, envíos).
@router.post("", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(enforce_rate_limit)])
def create_message(
    body: MessageIn,
    app_id: CurrentAppId,
    use_case: Annotated[CreateMessage, Depends(container.create_message)],
    response: Response,
    idempotency_key: IdempotencyKey = None,
) -> MessageAccepted:
    """Con `Idempotency-Key`, repetir la petición devuelve el mismo mensaje sin crear otro."""
    try:
        result = use_case.execute(app_id, body.event_type, body.payload, idempotency_key)
    except IdempotencyKeyReused:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La Idempotency-Key ya se usó con otro evento o payload",
        ) from None
    if result.replayed:
        # Para que el cliente sepa que no se creó nada nuevo (como hace Stripe).
        response.headers["Idempotent-Replayed"] = "true"
    return MessageAccepted(id=result.message.id)


@router.get("")
def list_messages(
    app_id: CurrentAppId,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
    event_type: Annotated[EventType | None, Query()] = None,
) -> MessagePage:
    """Los mensajes de la aplicación, del más nuevo al más viejo.

    Para la página siguiente, repite la petición con `cursor=next_cursor`.
    """
    try:
        before = None if cursor is None else decode_cursor(cursor)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Cursor inválido"
        ) from None

    rows, has_more = queries.list_messages(session, app_id, limit, before, event_type)
    last = rows[-1] if rows else None
    return MessagePage(
        data=[MessageSummary(**row) for row in rows],
        next_cursor=encode_cursor(last["created_at"], last["id"]) if has_more and last else None,
    )


@router.get("/{message_id}")
def get_message(message_id: UUID, app_id: CurrentAppId, session: SessionDep) -> MessageOut:
    message = queries.get_message(session, app_id, message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado")
    return MessageOut(**message)


@router.get("/{message_id}/attempts")
def list_attempts(message_id: UUID, app_id: CurrentAppId, session: SessionDep) -> list[AttemptOut]:
    attempts = queries.list_attempts(session, app_id, message_id)
    if attempts is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado")
    return [AttemptOut(**attempt) for attempt in attempts]
