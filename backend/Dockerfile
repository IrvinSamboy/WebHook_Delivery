FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir -e ".[dev]"

# UID 1000 para que los archivos creados en el volumen montado sean editables desde el host.
RUN useradd --uid 1000 --create-home relay
USER relay

EXPOSE 8000
CMD ["uvicorn", "relay.entrypoints.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
