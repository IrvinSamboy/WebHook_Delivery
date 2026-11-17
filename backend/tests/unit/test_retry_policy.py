from datetime import timedelta

import pytest

from relay.domain.retry_policy import MAX_RETRY_AFTER, RetryPolicy


def lowest(a: float, b: float) -> float:
    return a


def highest(a: float, b: float) -> float:
    return b


def no_jitter(a: float, b: float) -> float:
    return 1.0


@pytest.mark.parametrize(
    ("attempt", "expected_seconds"),
    [
        pytest.param(1, 30, id="tras-el-1º-30s"),
        pytest.param(2, 60, id="tras-el-2º-1min"),
        pytest.param(3, 120, id="tras-el-3º-2min"),
        pytest.param(9, 7680, id="tras-el-9º-128min"),
    ],
)
def test_la_espera_se_duplica_en_cada_intento(attempt, expected_seconds):
    policy = RetryPolicy(base_seconds=30, jitter=no_jitter)

    assert policy.delay_after(attempt) == timedelta(seconds=expected_seconds)


@pytest.mark.parametrize("attempt", range(1, 10))
def test_el_jitter_varia_la_espera_un_20_por_ciento_como_maximo(attempt):
    base = 30 * 2 ** (attempt - 1)

    shortest = RetryPolicy(base_seconds=30, jitter=lowest).delay_after(attempt)
    longest = RetryPolicy(base_seconds=30, jitter=highest).delay_after(attempt)

    assert shortest == timedelta(seconds=base * 0.8)
    assert longest == timedelta(seconds=base * 1.2)


def test_el_jitter_por_defecto_es_aleatorio_y_esta_en_rango():
    policy = RetryPolicy(base_seconds=30)

    delays = {policy.delay_after(1) for _ in range(50)}

    assert len(delays) > 1
    assert all(timedelta(seconds=24) <= d <= timedelta(seconds=36) for d in delays)


def test_respeta_un_retry_after_mayor_que_el_backoff():
    policy = RetryPolicy(base_seconds=30, jitter=no_jitter)

    assert policy.delay_after(1, retry_after=timedelta(minutes=10)) == timedelta(minutes=10)


def test_ignora_un_retry_after_menor_que_el_backoff():
    policy = RetryPolicy(base_seconds=30, jitter=no_jitter)

    assert policy.delay_after(3, retry_after=timedelta(seconds=5)) == timedelta(minutes=2)


def test_limita_un_retry_after_exagerado():
    policy = RetryPolicy(base_seconds=30, jitter=no_jitter)

    assert policy.delay_after(1, retry_after=timedelta(days=30)) == MAX_RETRY_AFTER
