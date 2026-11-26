from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from relay.config import get_settings
from relay.entrypoints.api.routers import deliveries, endpoints, messages


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_settings()  # Si falta configuración, la API no llega a arrancar.
    yield


app = FastAPI(title="webhook-relay", version="0.1.0", lifespan=lifespan)
app.include_router(endpoints.router)
app.include_router(messages.router)
app.include_router(deliveries.router)

# Panel web mínimo en /ui: mismo origen que la API, así que no hace falta CORS.
app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
