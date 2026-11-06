"""Composition root: el único lugar que conecta puertos con implementaciones."""

from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from relay.application.use_cases.create_application import CreateApplication
from relay.application.use_cases.create_message import CreateMessage
from relay.application.use_cases.register_endpoint import RegisterEndpoint
from relay.config import get_settings
from relay.infrastructure.clock import SystemClock
from relay.infrastructure.db.session import build_session_factory
from relay.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


@lru_cache
def session_factory() -> sessionmaker[Session]:
    return build_session_factory(get_settings().database_url)


def create_application() -> CreateApplication:
    return CreateApplication(SqlAlchemyUnitOfWork(session_factory()), SystemClock())


def register_endpoint() -> RegisterEndpoint:
    return RegisterEndpoint(SqlAlchemyUnitOfWork(session_factory()), SystemClock())


def create_message() -> CreateMessage:
    return CreateMessage(SqlAlchemyUnitOfWork(session_factory()), SystemClock())
