"""El rate limiter contra Redis real (base 15, que se vacía tras cada test)."""

from uuid import uuid4

import pytest
import redis

from relay.config import get_settings
from relay.infrastructure.rate_limiter import RedisRateLimiter

TEST_DB = 15


@pytest.fixture
def client():
    url = get_settings().redis_url.rsplit("/", 1)[0] + f"/{TEST_DB}"
    client = redis.Redis.from_url(url)
    client.flushdb()
    yield client
    client.flushdb()  # Solo la base 15: la cola de Celery (base 0) no se toca.
    client.close()


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_deja_pasar_hasta_el_limite_y_luego_no(client):
    limiter = RedisRateLimiter(client, limit=3, now=Clock(1_000_020.0))
    app_id = uuid4()

    decisions = [limiter.hit(app_id) for _ in range(4)]

    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions] == [2, 1, 0, 0]


def test_dice_cuanto_falta_para_la_ventana_siguiente(client):
    # 1_000_040 = 16_667 × 60 + 20: van 20 s del minuto, faltan 40.
    limiter = RedisRateLimiter(client, limit=3, now=Clock(1_000_040.0))

    assert limiter.hit(uuid4()).reset_seconds == 40


def test_cada_minuto_empieza_de_cero(client):
    clock = Clock(1_000_020.0)
    limiter = RedisRateLimiter(client, limit=1, now=clock)
    app_id = uuid4()
    limiter.hit(app_id)
    assert limiter.hit(app_id).allowed is False

    clock.now += 60

    assert limiter.hit(app_id).allowed is True


def test_cada_aplicacion_tiene_su_propio_contador(client):
    limiter = RedisRateLimiter(client, limit=1, now=Clock(1_000_020.0))
    first, second = uuid4(), uuid4()
    limiter.hit(first)

    assert limiter.hit(first).allowed is False
    assert limiter.hit(second).allowed is True


def test_la_clave_caduca_sola(client):
    limiter = RedisRateLimiter(client, limit=5, now=Clock(1_000_020.0))
    app_id = uuid4()

    limiter.hit(app_id)
    limiter.hit(app_id)

    [key] = client.keys(f"ratelimit:{app_id}:*")
    # Sin caducidad, Redis acumularía una clave por aplicación y minuto para siempre.
    assert 0 < client.ttl(key) <= 60


def test_varios_procesos_cuentan_sobre_el_mismo_contador(client):
    # Dos limitadores = dos procesos de la API. INCR es atómico en Redis.
    app_id = uuid4()
    a = RedisRateLimiter(client, limit=3, now=Clock(1_000_020.0))
    b = RedisRateLimiter(client, limit=3, now=Clock(1_000_020.0))

    results = [a.hit(app_id).allowed, b.hit(app_id).allowed, a.hit(app_id).allowed]

    assert results == [True, True, True]
    assert b.hit(app_id).allowed is False


def test_si_redis_no_responde_deja_pasar():
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)

    decision = RedisRateLimiter(dead, limit=1).hit(uuid4())

    assert decision.allowed is True
    assert decision.remaining is None
