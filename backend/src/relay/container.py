"""Composition root: el único lugar que conecta puertos con implementaciones."""

from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from relay.application.use_cases.create_application import CreateApplication
from relay.application.use_cases.create_message import CreateMessage
from relay.application.use_cases.deliver_message import DeliverMessage
from relay.application.use_cases.recover_stuck_deliveries import RecoverStuckDeliveries
from relay.application.use_cases.register_endpoint import RegisterEndpoint
from relay.application.use_cases.retry_delivery import RetryDelivery
from relay.application.use_cases.schedule_due_deliveries import ScheduleDueDeliveries
from relay.config import get_settings
from relay.domain.retry_policy import RetryPolicy
from relay.infrastructure.clock import SystemClock
from relay.infrastructure.crypto import SecretCipher
from relay.infrastructure.db.session import build_session_factory
from relay.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from relay.infrastructure.http_sender import Httpx2Sender
from relay.infrastructure.queue.celery_app import app as celery_app
from relay.infrastructure.queue.task_queue import CeleryTaskQueue


@lru_cache
def session_factory() -> sessionmaker[Session]:
    return build_session_factory(get_settings().database_url)


@lru_cache
def secret_cipher() -> SecretCipher:
    return SecretCipher(get_settings().encryption_key.get_secret_value())


@lru_cache
def http_sender() -> Httpx2Sender:
    # Uno por proceso: reutiliza las conexiones abiertas con los receptores.
    return Httpx2Sender()


def task_queue() -> CeleryTaskQueue:
    return CeleryTaskQueue(celery_app)


def _unit_of_work() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory(), secret_cipher())


def create_application() -> CreateApplication:
    return CreateApplication(_unit_of_work(), SystemClock())


def register_endpoint() -> RegisterEndpoint:
    return RegisterEndpoint(_unit_of_work(), SystemClock())


def create_message() -> CreateMessage:
    return CreateMessage(_unit_of_work(), SystemClock(), task_queue())


def retry_policy() -> RetryPolicy:
    return RetryPolicy(base_seconds=get_settings().backoff_base_seconds)


def deliver_message() -> DeliverMessage:
    return DeliverMessage(_unit_of_work(), http_sender(), SystemClock(), retry_policy())


def schedule_due_deliveries() -> ScheduleDueDeliveries:
    return ScheduleDueDeliveries(_unit_of_work(), SystemClock(), task_queue())


def recover_stuck_deliveries() -> RecoverStuckDeliveries:
    return RecoverStuckDeliveries(_unit_of_work())


def retry_delivery() -> RetryDelivery:
    return RetryDelivery(_unit_of_work(), SystemClock(), task_queue())
