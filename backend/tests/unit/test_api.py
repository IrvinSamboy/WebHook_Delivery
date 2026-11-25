"""Prueba la capa HTTP: códigos de respuesta, autenticación y validación."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from fakes import FakeClock, FakeDestinationGuard, FakeTaskQueue, FakeUnitOfWork, make_endpoint
from relay.domain.delivery_status import DeliveryStatus
from relay.domain.entities import Delivery, Message
from relay import container
from relay.application.use_cases.create_message import CreateMessage
from relay.application.use_cases.register_endpoint import RegisterEndpoint
from relay.application.use_cases.retry_delivery import RetryDelivery
from relay.application.use_cases.rotate_endpoint_secret import RotateEndpointSecret
from relay.application.use_cases.update_endpoint import UpdateEndpoint
from relay.domain.api_keys import hash_api_key, prefix_of
from relay.entrypoints.api import deps
from relay.entrypoints.api.main import app
from relay.entrypoints.api.pagination import decode_cursor, encode_cursor
from relay.infrastructure.db import queries

APP_ID = uuid4()
API_KEY = "whr_prueba.secreto-valido"
AUTH = {"Authorization": f"Bearer {API_KEY}"}
VALID_MESSAGE = {"event_type": "order.paid", "payload": {"order_id": "ord_981"}}
INTERNAL_URL = "http://169.254.169.254/latest/meta-data/"
BLOCKING_GUARD = FakeDestinationGuard(blocked={INTERNAL_URL})
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
        container.register_endpoint: lambda: RegisterEndpoint(uow, FakeClock(), BLOCKING_GUARD),
        container.retry_delivery: lambda: RetryDelivery(uow, FakeClock(), FakeTaskQueue()),
        container.update_endpoint: lambda: UpdateEndpoint(uow, BLOCKING_GUARD),
        container.rotate_endpoint_secret: lambda: RotateEndpointSecret(uow, FakeClock()),
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
        pytest.param("GET", "/v1/endpoints", None, id="listar-endpoints"),
        pytest.param("GET", f"/v1/endpoints/{uuid4()}", None, id="leer-endpoint"),
        pytest.param("PATCH", f"/v1/endpoints/{uuid4()}", {"enabled": False}, id="editar-endpoint"),
        pytest.param("POST", f"/v1/endpoints/{uuid4()}/rotate-secret", None, id="rotar-secreto"),
        pytest.param("GET", "/v1/messages", None, id="listar-mensajes"),
        pytest.param("GET", f"/v1/endpoints/{uuid4()}/stats", None, id="estadisticas"),
        pytest.param("GET", f"/v1/messages/{uuid4()}/attempts", None, id="leer-intentos"),
        pytest.param("POST", f"/v1/deliveries/{uuid4()}/retry", None, id="reintentar"),
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


# --- POST /v1/deliveries/{id}/retry ---


def add_delivery(uow, status, app_id=APP_ID) -> Delivery:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    message = Message(id=uuid4(), app_id=app_id, event_type="order.paid", payload={}, created_at=now)
    delivery = Delivery(
        id=uuid4(),
        message_id=message.id,
        endpoint_id=uuid4(),
        status=status,
        next_attempt_at=now,
        created_at=now,
        attempt_count=10,
    )
    uow.messages.add(message)
    uow.deliveries.add(delivery)
    return delivery


def test_reintentar_una_entrega_fallida_responde_202(client, uow):
    delivery = add_delivery(uow, DeliveryStatus.FAILED)

    response = client.post(f"/v1/deliveries/{delivery.id}/retry", headers=AUTH)

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["attempt_count"] == 10


def test_reintentar_una_entrega_que_no_fallo_responde_409(client, uow):
    delivery = add_delivery(uow, DeliveryStatus.SUCCEEDED)

    response = client.post(f"/v1/deliveries/{delivery.id}/retry", headers=AUTH)

    assert response.status_code == 409
    assert "succeeded" in response.json()["detail"]


@pytest.mark.parametrize("de_otra_app", [False, True], ids=["inexistente", "de-otra-aplicacion"])
def test_reintentar_una_entrega_ajena_o_inexistente_responde_404(client, uow, de_otra_app):
    delivery_id = add_delivery(uow, DeliveryStatus.FAILED, app_id=uuid4()).id if de_otra_app else uuid4()

    response = client.post(f"/v1/deliveries/{delivery_id}/retry", headers=AUTH)

    assert response.status_code == 404


# --- GET /v1/messages/{id}/attempts ---


def test_leer_intentos_responde_200_y_filtra_por_aplicacion(client, monkeypatch):
    message_id = uuid4()
    calls = []
    attempt = {
        "id": uuid4(),
        "delivery_id": uuid4(),
        "endpoint_id": uuid4(),
        "number": 1,
        "trigger": "auto",
        "started_at": datetime(2026, 1, 1, tzinfo=UTC),
        "duration_ms": 85,
        "request_headers": {"webhook-id": str(message_id)},
        "response_status": 500,
        "response_body": "down",
        "error": None,
    }

    def fake_list_attempts(_session, app_id, requested_id):
        calls.append((app_id, requested_id))
        return [attempt]

    monkeypatch.setattr(queries, "list_attempts", fake_list_attempts)

    response = client.get(f"/v1/messages/{message_id}/attempts", headers=AUTH)

    assert response.status_code == 200
    assert calls == [(APP_ID, message_id)]
    [body] = response.json()
    assert body["response_status"] == 500
    assert body["trigger"] == "auto"


def test_leer_intentos_de_un_mensaje_sin_intentos_devuelve_lista_vacia(client, monkeypatch):
    monkeypatch.setattr(queries, "list_attempts", lambda *_: [])

    response = client.get(f"/v1/messages/{uuid4()}/attempts", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == []


def test_leer_intentos_de_un_mensaje_ajeno_o_inexistente_responde_404(client, monkeypatch):
    monkeypatch.setattr(queries, "list_attempts", lambda *_: None)

    response = client.get(f"/v1/messages/{uuid4()}/attempts", headers=AUTH)

    assert response.status_code == 404


# --- GET /v1/endpoints y GET /v1/endpoints/{id} ---


def endpoint_row(endpoint_id=None):
    return {
        "id": endpoint_id or uuid4(),
        "url": "https://example.com/webhook",
        "event_types": ["order.paid"],
        "enabled": True,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "previous_secret_expires_at": None,
    }


def test_listar_endpoints_responde_200_y_filtra_por_aplicacion(client, monkeypatch):
    calls = []

    def fake_list_endpoints(_session, app_id):
        calls.append(app_id)
        return [endpoint_row(), endpoint_row()]

    monkeypatch.setattr(queries, "list_endpoints", fake_list_endpoints)

    response = client.get("/v1/endpoints", headers=AUTH)

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert calls == [APP_ID]


def test_leer_endpoint_nunca_muestra_el_secreto(client, monkeypatch):
    endpoint_id = uuid4()
    # Aunque la consulta devolviera el secreto por error, la respuesta no lo incluye.
    monkeypatch.setattr(
        queries, "get_endpoint", lambda *_: {**endpoint_row(endpoint_id), "secret": "whsec_x"}
    )

    response = client.get(f"/v1/endpoints/{endpoint_id}", headers=AUTH)

    assert response.status_code == 200
    assert set(response.json()) == {
        "id",
        "url",
        "event_types",
        "enabled",
        "created_at",
        "previous_secret_expires_at",
    }


def test_leer_endpoint_inexistente_responde_404(client, monkeypatch):
    monkeypatch.setattr(queries, "get_endpoint", lambda *_: None)

    response = client.get(f"/v1/endpoints/{uuid4()}", headers=AUTH)

    assert response.status_code == 404


# --- PATCH /v1/endpoints/{id} ---


def test_editar_endpoint_responde_200_con_el_resultado(client, uow):
    endpoint = uow.endpoints.items[0]

    response = client.patch(
        f"/v1/endpoints/{endpoint.id}",
        json={"url": "https://nueva.com/hook", "enabled": False},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["url"] == "https://nueva.com/hook"
    assert response.json()["enabled"] is False
    assert "secret" not in response.json()
    assert uow.endpoints.items[0].url == "https://nueva.com/hook"


def test_editar_endpoint_de_otra_aplicacion_responde_404(client, uow):
    ajeno = make_endpoint(app_id=uuid4())
    uow.endpoints.items.append(ajeno)

    response = client.patch(f"/v1/endpoints/{ajeno.id}", json={"enabled": False}, headers=AUTH)

    assert response.status_code == 404
    assert ajeno.enabled is True


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="vacio"),
        pytest.param({"url": None}, id="url-null"),
        pytest.param({"enabled": None}, id="enabled-null"),
        pytest.param({"url": "no-es-url"}, id="url-invalida"),
        pytest.param({"event_types": []}, id="sin-eventos"),
        pytest.param({"event_types": ["con espacio"]}, id="evento-invalido"),
        # Con un campo válido al lado: si no, fallaría solo por ir vacío.
        pytest.param({"enabled": False, "secret": "whsec_x"}, id="campo-desconocido"),
    ],
)
def test_editar_endpoint_responde_422_con_body_invalido(client, uow, body):
    endpoint = uow.endpoints.items[0]

    response = client.patch(f"/v1/endpoints/{endpoint.id}", json=body, headers=AUTH)

    assert response.status_code == 422
    assert uow.committed is False


# --- POST /v1/endpoints/{id}/rotate-secret ---


def test_rotar_secreto_devuelve_el_nuevo_y_hasta_cuando_vale_el_anterior(client, uow):
    endpoint = uow.endpoints.items[0]
    old_secret = endpoint.secret

    response = client.post(f"/v1/endpoints/{endpoint.id}/rotate-secret", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["secret"].startswith("whsec_")
    assert body["secret"] != old_secret
    assert body["secret"] == uow.endpoints.items[0].secret
    assert body["previous_secret_expires_at"] == "2026-01-02T12:00:00Z"  # NOW + 24 h


def test_rotar_secreto_con_expire_previous_lo_invalida_ya(client, uow):
    endpoint = uow.endpoints.items[0]

    response = client.post(
        f"/v1/endpoints/{endpoint.id}/rotate-secret?expire_previous=true", headers=AUTH
    )

    assert response.status_code == 200
    assert response.json()["previous_secret_expires_at"] is None
    assert uow.endpoints.items[0].previous_secret is None


def test_rotar_secreto_de_otra_aplicacion_responde_404(client, uow):
    ajeno = make_endpoint(app_id=uuid4())
    uow.endpoints.items.append(ajeno)
    old_secret = ajeno.secret

    response = client.post(f"/v1/endpoints/{ajeno.id}/rotate-secret", headers=AUTH)

    assert response.status_code == 404
    assert uow.endpoints.items[-1].secret == old_secret


# --- GET /v1/messages ---


def message_row(created_at=None):
    return {
        "id": uuid4(),
        "event_type": "order.paid",
        "payload": {"n": 1},
        "created_at": created_at or datetime(2026, 1, 1, tzinfo=UTC),
    }


class FakeListMessages:
    """Sustituye la consulta: guarda cómo se la llamó y devuelve `result`."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.result: tuple[list, bool] = ([], False)

    def __call__(self, _session, app_id, limit, before, event_type):
        self.calls.append(
            {"app_id": app_id, "limit": limit, "before": before, "event_type": event_type}
        )
        return self.result


@pytest.fixture
def list_messages(monkeypatch):
    fake = FakeListMessages()
    monkeypatch.setattr(queries, "list_messages", fake)
    return fake


def test_listar_mensajes_usa_valores_por_defecto(client, list_messages):
    response = client.get("/v1/messages", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"data": [], "next_cursor": None}
    assert list_messages.calls == [{"app_id": APP_ID, "limit": 50, "before": None, "event_type": None}]


def test_si_quedan_mas_el_cursor_apunta_al_ultimo_de_la_pagina(client, list_messages):
    rows = [message_row(), message_row()]
    list_messages.result = (rows, True)

    response = client.get("/v1/messages?limit=2", headers=AUTH)

    cursor = response.json()["next_cursor"]
    assert decode_cursor(cursor) == (rows[-1]["created_at"], rows[-1]["id"])
    assert [m["id"] for m in response.json()["data"]] == [str(r["id"]) for r in rows]


def test_en_la_ultima_pagina_no_hay_cursor(client, list_messages):
    list_messages.result = ([message_row()], False)

    response = client.get("/v1/messages", headers=AUTH)

    assert response.json()["next_cursor"] is None


def test_el_cursor_y_el_filtro_llegan_a_la_consulta(client, list_messages):
    position = (datetime(2026, 1, 1, tzinfo=UTC), uuid4())
    cursor = encode_cursor(*position)

    client.get(f"/v1/messages?cursor={cursor}&event_type=order.paid&limit=10", headers=AUTH)

    assert list_messages.calls[0]["before"] == position
    assert list_messages.calls[0]["event_type"] == "order.paid"
    assert list_messages.calls[0]["limit"] == 10


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("limit=0", id="limit-0"),
        pytest.param("limit=101", id="limit-101"),
        pytest.param("cursor=basura", id="cursor-invalido"),
        pytest.param("event_type=con%20espacio", id="evento-invalido"),
    ],
)
def test_listar_mensajes_responde_422_con_parametros_invalidos(client, list_messages, query):
    response = client.get(f"/v1/messages?{query}", headers=AUTH)

    assert response.status_code == 422
    assert list_messages.calls == []


# --- GET /v1/endpoints/{id}/stats ---


def test_estadisticas_responde_200_y_filtra_por_aplicacion(client, monkeypatch):
    endpoint_id = uuid4()
    calls = []
    stats = {
        "since": datetime(2026, 1, 1, tzinfo=UTC),
        "deliveries": {"pending": 1, "queued": 0, "sending": 0, "succeeded": 3, "failed": 1},
        "success_rate": 0.75,
    }

    def fake_stats(_session, app_id, requested_id):
        calls.append((app_id, requested_id))
        return stats

    monkeypatch.setattr(queries, "endpoint_stats", fake_stats)

    response = client.get(f"/v1/endpoints/{endpoint_id}/stats", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["success_rate"] == 0.75
    assert calls == [(APP_ID, endpoint_id)]


def test_estadisticas_de_un_endpoint_ajeno_responde_404(client, monkeypatch):
    monkeypatch.setattr(queries, "endpoint_stats", lambda *_: None)

    response = client.get(f"/v1/endpoints/{uuid4()}/stats", headers=AUTH)

    assert response.status_code == 404


# --- Protección contra SSRF ---


def test_registrar_un_endpoint_interno_responde_422_sin_revelar_la_ip(client, uow):
    before = len(uow.endpoints.items)

    response = client.post(
        "/v1/endpoints", json={"url": INTERNAL_URL, "event_types": ["order.paid"]}, headers=AUTH
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Destino no permitido: apunta a una dirección interna"
    assert len(uow.endpoints.items) == before


def test_cambiar_la_url_a_una_interna_responde_422(client, uow):
    endpoint = uow.endpoints.items[0]

    response = client.patch(f"/v1/endpoints/{endpoint.id}", json={"url": INTERNAL_URL}, headers=AUTH)

    assert response.status_code == 422
    assert uow.endpoints.items[0].url == endpoint.url
