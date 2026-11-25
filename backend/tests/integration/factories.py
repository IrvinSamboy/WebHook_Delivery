"""Crean filas directamente con los modelos: cada test indica solo lo que le importa.

Van por los modelos y no por los casos de uso para poder fijar estados y
horas concretas (una entrega pending desde hace una hora, por ejemplo).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from relay.infrastructure.db.models import (
    ApplicationModel,
    DeliveryModel,
    EndpointModel,
    MessageModel,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def add_app(session: Session) -> UUID:
    app_id = uuid4()
    session.add(ApplicationModel(id=app_id, name="tienda", created_at=NOW))
    session.flush()
    return app_id


def add_endpoint(session: Session, app_id: UUID, **fields: Any) -> UUID:
    endpoint_id = uuid4()
    session.add(
        EndpointModel(
            **{
                "id": endpoint_id,
                "app_id": app_id,
                "url": "https://example.com/hook",
                "secret_encrypted": "no-se-usa",
                "event_types": ["order.paid"],
                "enabled": True,
                "created_at": NOW,
                **fields,
            }
        )
    )
    session.flush()
    return endpoint_id


def add_message(session: Session, app_id: UUID, **fields: Any) -> UUID:
    message_id = uuid4()
    session.add(
        MessageModel(
            **{
                "id": message_id,
                "app_id": app_id,
                "event_type": "order.paid",
                "payload": {},
                "created_at": NOW,
                **fields,
            }
        )
    )
    session.flush()
    return message_id


def add_delivery(session: Session, endpoint_id: UUID, app_id: UUID, **fields: Any) -> UUID:
    """Crea la entrega con su propio mensaje (una entrega por mensaje y endpoint)."""
    delivery_id = uuid4()
    session.add(
        DeliveryModel(
            **{
                "id": delivery_id,
                "message_id": add_message(session, app_id),
                "endpoint_id": endpoint_id,
                "status": "pending",
                "next_attempt_at": NOW,
                **fields,
            }
        )
    )
    session.flush()
    return delivery_id


def age(session: Session, delivery_id: UUID, minutes: int) -> None:
    """Hace que la entrega parezca llevar `minutes` sin cambiar de estado.

    updated_at lo pone Postgres con now(): se retrocede con SQL.
    """
    session.execute(
        text("UPDATE deliveries SET updated_at = now() - make_interval(mins => :m) WHERE id = :id"),
        {"m": minutes, "id": delivery_id},
    )


def status_of(session: Session, delivery_id: UUID) -> str:
    return session.scalar(text("SELECT status FROM deliveries WHERE id = :id"), {"id": delivery_id})
