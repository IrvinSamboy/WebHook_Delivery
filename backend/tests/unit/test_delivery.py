"""Reglas de la máquina de estados de una entrega."""

from datetime import timedelta
from uuid import uuid4

import pytest

from fakes import NOW
from relay.domain.delivery_status import ALLOWED_TRANSITIONS, DeliveryStatus
from relay.domain.entities import Delivery
from relay.domain.errors import InvalidTransition
from relay.domain.retry_policy import RetryPolicy

POLICY = RetryPolicy(base_seconds=30, max_attempts=10, jitter=lambda a, b: 1.0)
LATER = NOW + timedelta(hours=1)
# La "tarjeta" del worker que tiene el sobre en los tests de intentos.
LEASE = uuid4()


def make_delivery(status: DeliveryStatus = DeliveryStatus.SENDING, attempt_count: int = 0):
    return Delivery(
        id=uuid4(),
        message_id=uuid4(),
        endpoint_id=uuid4(),
        status=status,
        next_attempt_at=NOW,
        created_at=NOW,
        attempt_count=attempt_count,
        lease_id=LEASE if status is DeliveryStatus.SENDING else None,
    )


# --- Tomar el sobre de la cola ---


def test_un_worker_puede_tomar_un_sobre_encolado():
    delivery = make_delivery(DeliveryStatus.QUEUED)

    delivery.start_sending()

    assert delivery.status is DeliveryStatus.SENDING


@pytest.mark.parametrize(
    "status",
    [s for s in DeliveryStatus if s is not DeliveryStatus.QUEUED],
)
def test_solo_se_envian_sobres_encolados(status):
    # Un sobre pending está esperando su turno: enviarlo se saltaría el backoff.
    delivery = make_delivery(status)

    with pytest.raises(InvalidTransition):
        delivery.start_sending()

    assert delivery.status is status


# --- Qué pasa tras un intento ---


def test_un_exito_cierra_el_sobre():
    delivery = make_delivery()

    delivery.record_attempt(lease_id=LEASE, succeeded=True, now=LATER, policy=POLICY)

    assert delivery.status is DeliveryStatus.SUCCEEDED
    assert delivery.attempt_count == 1


def test_un_fallo_con_intentos_restantes_reprograma_el_sobre():
    delivery = make_delivery(attempt_count=2)

    delivery.record_attempt(lease_id=LEASE, succeeded=False, now=LATER, policy=POLICY)

    assert delivery.status is DeliveryStatus.PENDING
    assert delivery.attempt_count == 3
    # Tras el 3er intento fallido: 30 s × 2² = 2 minutos.
    assert delivery.next_attempt_at == LATER + timedelta(minutes=2)


def test_el_retry_after_del_receptor_retrasa_el_reintento():
    delivery = make_delivery()

    delivery.record_attempt(
        lease_id=LEASE,
        succeeded=False,
        now=LATER,
        policy=POLICY,
        retry_after=timedelta(minutes=5),
    )

    assert delivery.next_attempt_at == LATER + timedelta(minutes=5)


def test_el_ultimo_intento_fallido_marca_el_sobre_como_fallido():
    delivery = make_delivery(attempt_count=9)

    delivery.record_attempt(lease_id=LEASE, succeeded=False, now=LATER, policy=POLICY)

    assert delivery.status is DeliveryStatus.FAILED
    assert delivery.attempt_count == 10


def test_el_ultimo_intento_tambien_puede_tener_exito():
    delivery = make_delivery(attempt_count=9)

    delivery.record_attempt(lease_id=LEASE, succeeded=True, now=LATER, policy=POLICY)

    assert delivery.status is DeliveryStatus.SUCCEEDED


def test_un_reintento_manual_fallido_no_empieza_otra_ronda():
    # Tras agotar los 10 intentos, un reintento manual es un único intento extra.
    delivery = make_delivery(attempt_count=10)

    delivery.record_attempt(lease_id=LEASE, succeeded=False, now=LATER, policy=POLICY)

    assert delivery.status is DeliveryStatus.FAILED
    assert delivery.attempt_count == 11


# --- El lease (fencing token) ---


def test_cada_vez_que_se_toma_el_sobre_hay_un_lease_nuevo():
    delivery = make_delivery(DeliveryStatus.QUEUED)

    first = delivery.start_sending()
    delivery.status = DeliveryStatus.QUEUED  # Como si el reaper y el scheduler la devolvieran.
    second = delivery.start_sending()

    assert first != second
    assert delivery.lease_id == second


def test_con_el_lease_vigente_se_decide_el_estado_y_el_lease_se_libera():
    delivery = make_delivery()

    valid = delivery.record_attempt(lease_id=LEASE, succeeded=True, now=LATER, policy=POLICY)

    assert valid is True
    assert delivery.status is DeliveryStatus.SUCCEEDED
    assert delivery.lease_id is None


def test_con_un_lease_caducado_solo_se_cuenta_el_intento():
    # Otro worker tomó el sobre mientras este estaba congelado.
    delivery = make_delivery(attempt_count=3)
    delivery.lease_id = uuid4()
    other_lease, before = delivery.lease_id, delivery.next_attempt_at

    valid = delivery.record_attempt(lease_id=LEASE, succeeded=False, now=LATER, policy=POLICY)

    assert valid is False
    assert delivery.attempt_count == 4  # El POST ocurrió: cuenta para el máximo.
    assert delivery.status is DeliveryStatus.SENDING  # Lo sigue decidiendo el otro.
    assert delivery.lease_id == other_lease
    assert delivery.next_attempt_at == before


@pytest.mark.parametrize(
    "status",
    [s for s in DeliveryStatus if s is not DeliveryStatus.SENDING],
)
def test_si_el_sobre_ya_no_esta_en_envio_solo_se_cuenta_el_intento(status):
    # Por ejemplo, el reaper la devolvió a pending y borró el lease, u otro
    # worker ya terminó con ella.
    delivery = make_delivery(status)

    valid = delivery.record_attempt(lease_id=LEASE, succeeded=True, now=LATER, policy=POLICY)

    assert valid is False
    assert delivery.status is status
    assert delivery.attempt_count == 1


def test_un_lease_vacio_nunca_es_vigente():
    # Una entrega rescatada tiene lease None: nadie puede decidir con None.
    delivery = make_delivery()
    delivery.lease_id = None

    assert delivery.record_attempt(lease_id=LEASE, succeeded=True, now=LATER, policy=POLICY) is False


# --- La tabla de transiciones ---


def test_un_sobre_entregado_ya_no_cambia_de_estado():
    assert ALLOWED_TRANSITIONS[DeliveryStatus.SUCCEEDED] == frozenset()


def test_todos_los_estados_tienen_reglas():
    assert set(ALLOWED_TRANSITIONS) == set(DeliveryStatus)


# --- Reintento manual ---


def test_un_sobre_fallido_se_puede_reintentar_a_mano():
    delivery = make_delivery(DeliveryStatus.FAILED, attempt_count=10)

    delivery.retry_manually(LATER)

    assert delivery.status is DeliveryStatus.QUEUED
    assert delivery.next_attempt_at == LATER
    assert delivery.attempt_count == 10  # No se reinicia: es un intento extra.


@pytest.mark.parametrize(
    "status", [s for s in DeliveryStatus if s is not DeliveryStatus.FAILED]
)
def test_solo_se_reintenta_a_mano_lo_que_fallo(status):
    delivery = make_delivery(status)

    # Incluye pending: la tabla permite PENDING → QUEUED, pero eso es cosa del scheduler.
    with pytest.raises(InvalidTransition):
        delivery.retry_manually(LATER)

    assert delivery.status is status


def test_si_el_reintento_manual_falla_vuelve_a_failed_sin_mas_reintentos():
    delivery = make_delivery(DeliveryStatus.FAILED, attempt_count=10)
    delivery.retry_manually(LATER)
    lease_id = delivery.start_sending()

    delivery.record_attempt(lease_id=lease_id, succeeded=False, now=LATER, policy=POLICY)

    assert delivery.status is DeliveryStatus.FAILED
    assert delivery.attempt_count == 11
