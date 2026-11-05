from fastapi.testclient import TestClient

from relay.entrypoints.api.main import app


def test_health_responde_ok():
    # Preparar: un cliente que llama a la API sin levantar un servidor real.
    client = TestClient(app)

    # Ejecutar: hacer la petición.
    response = client.get("/health")

    # Comprobar: el código y el cuerpo son los esperados.
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
