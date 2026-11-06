import pytest

from fakes import make_endpoint


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
