"""Dependencias que FastAPI inyecta en los endpoints."""

from collections.abc import Callable, Iterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from relay import container
from relay.domain.api_keys import prefix_of, verify_api_key
from relay.infrastructure.db import queries

_bearer = HTTPBearer(auto_error=False)

ApiKeyFinder = Callable[[str], dict[str, Any] | None]


def get_session() -> Iterator[Session]:
    with container.session_factory()() as session:
        yield session


def get_api_key_finder() -> ApiKeyFinder:
    def find(prefix: str) -> dict[str, Any] | None:
        # Sesión propia y breve: no retiene una conexión durante toda la petición.
        with container.session_factory()() as session:
            return queries.find_api_key(session, prefix)

    return find


def get_current_app_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    find_api_key: Annotated[ApiKeyFinder, Depends(get_api_key_finder)],
) -> UUID:
    # El mismo error en todos los casos: no revela si un prefijo existe.
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API key inválida o ausente",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    api_key = credentials.credentials
    record = find_api_key(prefix_of(api_key))
    if record is None or not verify_api_key(api_key, record["key_hash"]):
        raise unauthorized

    return record["app_id"]


SessionDep = Annotated[Session, Depends(get_session)]
CurrentAppId = Annotated[UUID, Depends(get_current_app_id)]
