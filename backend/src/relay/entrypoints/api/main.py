from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from relay.config import get_settings
from relay.entrypoints.api.routers import endpoints, messages


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_settings()  # Si falta configuración, la API no llega a arrancar.
    yield


app = FastAPI(title="webhook-relay", version="0.1.0", lifespan=lifespan)
app.include_router(endpoints.router)
app.include_router(messages.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
