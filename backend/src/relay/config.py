from functools import lru_cache
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración leída de las variables de entorno.

    Los campos sin valor por defecto son obligatorios: si falta alguno o está
    vacío, la aplicación falla al arrancar en vez de fallar más tarde.
    """

    # Los mensajes de error no deben mostrar valores como contraseñas o claves.
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = Field(min_length=1)
    redis_url: str = Field(min_length=1)
    encryption_key: SecretStr
    # Espera tras el primer fallo; se duplica en cada reintento.
    backoff_base_seconds: float = Field(default=30, gt=0)
    # Permite enviar a direcciones internas. Solo para desarrollo (el receptor
    # de prueba es http://receiver:9000): por defecto, protegido contra SSRF.
    allow_private_urls: bool = False
    # Mensajes por minuto que puede crear cada aplicación.
    rate_limit_per_minute: int = Field(default=600, ge=1)

    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, value: SecretStr) -> SecretStr:
        Fernet(value.get_secret_value())  # Lanza ValueError si el formato no es válido.
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
