from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuración leída de las variables de entorno.

    Los campos sin valor por defecto son obligatorios: si falta alguno o está
    vacío, la aplicación falla al arrancar en vez de fallar más tarde.
    """

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = Field(min_length=1)
    redis_url: str = Field(min_length=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
