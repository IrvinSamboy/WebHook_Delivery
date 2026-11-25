"""Prueba de carga: muchos productores enviando eventos a la API.

    make load                                  # 50 usuarios durante 60 s
    make load users=200 duration=2m            # más presión
    make load delay=2                          # receptor que tarda 2 s
    make load-report                           # latencia de extremo a extremo

Al empezar se registra un endpoint que apunta al receptor de desarrollo; cada
usuario simulado envía mensajes (y de vez en cuando lista los últimos).
Locust mide la API; `make load-report` mide cuánto tardó cada webhook en llegar.
"""

import os
import uuid

import requests
from locust import FastHttpUser, between, events, task

API_KEY = os.environ["RELAY_API_KEY"]
AUTH = {"Authorization": f"Bearer {API_KEY}"}
EVENT_TYPE = "load.test"


@events.test_start.add_listener
def register_endpoint(environment, **_kwargs):
    response = requests.post(
        f"{environment.host}/v1/endpoints",
        json={"url": "http://receiver:9000/", "event_types": [EVENT_TYPE]},
        headers=AUTH,
        timeout=10,
    )
    response.raise_for_status()


class Producer(FastHttpUser):
    # Cada usuario espera entre 0,5 y 1,5 s entre peticiones (~1 petición/s).
    wait_time = between(0.5, 1.5)

    @task(10)
    def send_message(self):
        self.client.post(
            "/v1/messages",
            json={"event_type": EVENT_TYPE, "payload": {"order_id": str(uuid.uuid4())}},
            headers={**AUTH, "Idempotency-Key": str(uuid.uuid4())},
            name="POST /v1/messages",
        )

    @task(1)
    def list_messages(self):
        self.client.get("/v1/messages?limit=20", headers=AUTH, name="GET /v1/messages")
