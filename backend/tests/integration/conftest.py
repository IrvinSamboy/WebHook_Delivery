"""Tests de integración: contra un PostgreSQL real, en una base de datos aparte.

    make test-integration

Al empezar se crea la base `<nombre>_test` en el mismo servidor y se le aplican
las migraciones (así también se prueban desde cero). Tras cada test se vacían
las tablas. La base de desarrollo nunca se toca.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

from relay.config import get_settings
from relay.infrastructure.crypto import SecretCipher
from relay.infrastructure.db.models import Base
from relay.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

BACKEND_DIR = Path(__file__).parents[2]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Todo lo de esta carpeta es de integración: `make test` lo excluye.
    for item in items:
        if Path(item.fspath).is_relative_to(Path(__file__).parent):
            item.add_marker(pytest.mark.integration)


def alembic_config() -> Config:
    return Config(str(BACKEND_DIR / "alembic.ini"))


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    base_url = make_url(get_settings().database_url)
    url = base_url.set(database=f"{base_url.database}_test")
    # Salvaguarda: este fixture borra la base entera; que nunca sea otra.
    assert url.database.endswith("_test")

    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{url.database}"'))

    # migrations/env.py lee la URL de la configuración: se apunta a la de test.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    try:
        command.upgrade(alembic_config(), "head")
        yield os.environ["DATABASE_URL"]
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Iterator[Engine]:
    engine = create_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


@pytest.fixture(autouse=True)
def clean_tables(engine: Engine) -> Iterator[None]:
    yield
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture(scope="session")
def cipher() -> SecretCipher:
    return SecretCipher(Fernet.generate_key().decode())


@pytest.fixture
def uow(session_factory: sessionmaker[Session], cipher: SecretCipher) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory, cipher)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session
