"""Composition root: el único lugar que conecta puertos con implementaciones."""

from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from relay.application.use_cases.create_application import CreateApplication
from relay.application.use_cases.create_message import CreateMessage
from relay.application.use_cases.register_endpoint import RegisterEndpoint
from relay.config import get_settings
from relay.infrastructure.clock import SystemClock
from relay.infrastructure.crypto import SecretCipher
from relay.infrastructure.db.session import build_session_factory
from relay.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


@lru_cache
def session_factory() -> sessionmaker[Session]:
    return build_session_factory(get_settings().database_url)


@lru_cache
def secret_cipher() -> SecretCipher:
    return SecretCipher(get_settings().encryption_key.get_secret_value())


def _unit_of_work() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory(), secret_cipher())


def create_application() -> CreateApplication:
    return CreateApplication(_unit_of_work(), SystemClock())


def register_endpoint() -> RegisterEndpoint:
    return RegisterEndpoint(_unit_of_work(), SystemClock())


def create_message() -> CreateMessage:
    return CreateMessage(_unit_of_work(), SystemClock())
