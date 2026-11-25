"""Dependencias que FastAPI inyecta en los endpoints."""

from collections.abc import Callable, Iterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from relay import container
from relay.application.ports import RateLimiter
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


def enforce_rate_limit(
    app_id: CurrentAppId,
    response: Response,
    limiter: Annotated[RateLimiter, Depends(container.rate_limiter)],
) -> None:
    """Cuenta la petición; con el límite superado responde 429."""
    decision = limiter.hit(app_id)
    if decision.remaining is None:
        return  # Redis caído: se deja pasar sin cabeceras (no sabemos cuántas quedan).

    headers = {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_seconds),
    }
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados mensajes: espera antes de reintentar",
            headers={**headers, "Retry-After": str(decision.reset_seconds)},
        )
    response.headers.update(headers)
