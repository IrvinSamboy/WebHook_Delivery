import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from relay.config import Settings

VALID_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def valid_env(monkeypatch):
    """Parte de una configuración válida; cada test cambia solo lo que le importa."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")
    monkeypatch.setenv("ENCRYPTION_KEY", VALID_KEY)


def test_lee_la_configuracion_del_entorno():
    settings = Settings()

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.redis_url == "redis://cache:6379/0"
    assert settings.encryption_key.get_secret_value() == VALID_KEY


@pytest.mark.parametrize("name", ["DATABASE_URL", "REDIS_URL", "ENCRYPTION_KEY"])
def test_falla_si_falta_una_variable_obligatoria(monkeypatch, name):
    monkeypatch.delenv(name)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("name", ["DATABASE_URL", "REDIS_URL", "ENCRYPTION_KEY"])
def test_falla_si_una_variable_obligatoria_esta_vacia(monkeypatch, name):
    monkeypatch.setenv(name, "")

    with pytest.raises(ValidationError):
        Settings()


def test_falla_si_la_clave_de_cifrado_no_es_valida(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "clave-demasiado-corta")

    with pytest.raises(ValidationError) as error:
        Settings()

    assert "clave-demasiado-corta" not in str(error.value)


def test_la_clave_no_aparece_al_imprimir_la_configuracion():
    assert VALID_KEY not in repr(Settings())


def test_el_backoff_es_de_30_segundos_por_defecto(monkeypatch):
    monkeypatch.delenv("BACKOFF_BASE_SECONDS", raising=False)

    assert Settings().backoff_base_seconds == 30


@pytest.mark.parametrize("value", ["0", "-1", "rapido"])
def test_falla_si_el_backoff_no_es_un_numero_positivo(monkeypatch, value):
    monkeypatch.setenv("BACKOFF_BASE_SECONDS", value)

    with pytest.raises(ValidationError):
        Settings()
