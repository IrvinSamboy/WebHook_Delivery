import pytest
from pydantic import ValidationError

from relay.config import Settings


def test_lee_la_configuracion_del_entorno(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")

    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.redis_url == "redis://cache:6379/0"


def test_falla_si_falta_una_variable_obligatoria(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")

    with pytest.raises(ValidationError):
        Settings()


def test_falla_si_una_variable_obligatoria_esta_vacia(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")

    with pytest.raises(ValidationError):
        Settings()
