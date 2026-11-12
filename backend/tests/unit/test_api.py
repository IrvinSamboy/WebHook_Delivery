"""Prueba la capa HTTP: códigos de respuesta, autenticación y validación."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from fakes import FakeClock, FakeTaskQueue, FakeUnitOfWork, make_endpoint
from relay import container
from relay.application.use_cases.create_message import CreateMessage
from relay.application.use_cases.register_endpoint import RegisterEndpoint
from relay.domain.api_keys import hash_api_key, prefix_of
from relay.entrypoints.api import deps
from relay.entrypoints.api.main import app
from relay.infrastructure.db import queries

APP_ID = uuid4()
API_KEY = "whr_prueba.secreto-valido"
AUTH = {"Authorization": f"Bearer {API_KEY}"}
VALID_MESSAGE = {"event_type": "order.paid", "payload": {"order_id": "ord_981"}}
VALID_ENDPOINT = {"url": "https://example.com/webhook", "event_types": ["order.paid"]}


def fake_find_api_key(prefix: str):
    if prefix == prefix_of(API_KEY):
        return {"app_id": APP_ID, "key_hash": hash_api_key(API_KEY)}
    return None


@pytest.fixture
def uow():
    return FakeUnitOfWork(endpoints=[make_endpoint(app_id=APP_ID)])


@pytest.fixture
def client(uow):
    """Una API conectada a los fakes: estos tests no necesitan base de datos."""
    app.dependency_overrides = {
        deps.get_api_key_finder: lambda: fake_find_api_key,
        deps.get_session: lambda: None,
        container.create_message: lambda: CreateMessage(uow, FakeClock(), FakeTaskQueue()),
        container.register_endpoint: lambda: RegisterEndpoint(uow, FakeClock()),
    }
    yield TestClient(app)
    app.dependency_overrides = {}


# --- Autenticación ---


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="sin-header"),
        pytest.param({"Authorization": "Basic abc"}, id="otro-esquema"),
        pytest.param({"Authorization": "Bearer whr_otro.secreto"}, id="prefijo-desconocido"),
        pytest.param({"Authorization": "Bearer whr_prueba.incorrecto"}, id="secreto-incorrecto"),
    ],
)
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        pytest.param("POST", "/v1/messages", VALID_MESSAGE, id="crear-mensaje"),
        pytest.param("GET", f"/v1/messages/{uuid4()}", None, id="leer-mensaje"),
        pytest.param("POST", "/v1/endpoints", VALID_ENDPOINT, id="registrar-endpoint"),
    ],
)
def test_responde_401_sin_una_key_valida(client, uow, method, path, body, headers):
    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert uow.committed is False


# --- POST /v1/messages ---


def test_crear_mensaje_responde_202_y_lo_guarda(client, uow):
    response = client.post("/v1/messages", json=VALID_MESSAGE, headers=AUTH)

    assert response.status_code == 202
    assert response.json() == {"id": str(uow.messages.items[0].id)}
    assert uow.messages.items[0].app_id == APP_ID
    assert len(uow.deliveries.items) == 1


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"payload": {}}, id="sin-event-type"),
        pytest.param({"event_type": "order.paid"}, id="sin-payload"),
        pytest.param({"event_type": "", "payload": {}}, id="event-type-vacio"),
        pytest.param({"event_type": "con espacios", "payload": {}}, id="event-type-invalido"),
        pytest.param({"event_type": "a" * 201, "payload": {}}, id="event-type-largo"),
        pytest.param({"event_type": "order.paid", "payload": [1, 2]}, id="payload-no-es-objeto"),
        pytest.param({"event_type": "a.b", "payload": {"x": "a\x00b"}}, id="nul-en-valor"),
        pytest.param({"event_type": "a.b", "payload": {"a\x00": 1}}, id="nul-en-clave"),
        pytest.param({"event_type": "a.b", "payload": {"x": [{"y": "\x00"}]}}, id="nul-anidado"),
    ],
)
def test_crear_mensaje_responde_422_con_body_invalido(client, uow, body):
    response = client.post("/v1/messages", json=body, headers=AUTH)

    assert response.status_code == 422
    assert uow.messages.items == []


# --- POST /v1/endpoints ---


def test_registrar_endpoint_responde_201_con_el_secreto(client, uow):
    response = client.post("/v1/endpoints", json=VALID_ENDPOINT, headers=AUTH)

    assert response.status_code == 201
    saved = uow.endpoints.items[-1]
    assert saved.app_id == APP_ID
    assert response.json()["id"] == str(saved.id)
    assert response.json()["secret"] == saved.secret
    assert response.json()["url"] == "https://example.com/webhook"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"event_types": ["order.paid"]}, id="sin-url"),
        pytest.param({"url": "no-es-url", "event_types": ["order.paid"]}, id="url-invalida"),
        pytest.param({"url": "ftp://a.com/x", "event_types": ["order.paid"]}, id="esquema-ftp"),
        pytest.param({"url": "https://a.com/x", "event_types": []}, id="sin-eventos"),
    ],
)
def test_registrar_endpoint_responde_422_con_body_invalido(client, body):
    response = client.post("/v1/endpoints", json=body, headers=AUTH)

    assert response.status_code == 422


# --- GET /v1/messages/{id} ---


def test_leer_mensaje_responde_200_y_filtra_por_aplicacion(client, monkeypatch):
    message_id = uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    calls = []

    def fake_get_message(_session, app_id, requested_id):
        calls.append((app_id, requested_id))
        return {
            "id": requested_id,
            "event_type": "order.paid",
            "payload": {},
            "created_at": now,
            "deliveries": [],
        }

    monkeypatch.setattr(queries, "get_message", fake_get_message)

    response = client.get(f"/v1/messages/{message_id}", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["id"] == str(message_id)
    assert calls == [(APP_ID, message_id)]


def test_leer_mensaje_inexistente_responde_404(client, monkeypatch):
    monkeypatch.setattr(queries, "get_message", lambda *_: None)

    response = client.get(f"/v1/messages/{uuid4()}", headers=AUTH)

    assert response.status_code == 404


def test_leer_mensaje_con_id_invalido_responde_422(client):
    response = client.get("/v1/messages/no-es-un-uuid", headers=AUTH)

    assert response.status_code == 422
