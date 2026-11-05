from datetime import UTC, datetime
from uuid import uuid4

import pytest

from relay.domain.entities import Endpoint


def make_endpoint(event_types: list[str], enabled: bool = True) -> Endpoint:
    """Crea un endpoint válido; cada test solo indica lo que le importa."""
    return Endpoint(
        id=uuid4(),
        app_id=uuid4(),
        url="https://example.com/webhook",
        secret="whsec_c2VjcmV0",
        event_types=event_types,
        enabled=enabled,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("event_types", "enabled", "event_type", "expected"),
    [
        (["order.paid"], True, "order.paid", True),
        (["user.created", "order.paid"], True, "order.paid", True),
        (["user.created"], True, "order.paid", False),
        ([], True, "order.paid", False),
        (["order.paid"], False, "order.paid", False),
    ],
)
def test_accepts(event_types, enabled, event_type, expected):
    endpoint = make_endpoint(event_types, enabled)

    assert endpoint.accepts(event_type) is expected
