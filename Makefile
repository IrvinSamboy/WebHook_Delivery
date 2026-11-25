.PHONY: up down logs worker-logs beat-logs receiver test test-integration psql migrate migration create-app

.env:
	cp .env.example .env
	sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$$(openssl rand -base64 32 | tr '+/' '-_')|" .env

up: .env
	docker compose up -d --build

down:
	docker compose --profile dev down

logs:
	docker compose logs -f api

worker-logs:
	docker compose logs -f worker

beat-logs:
	docker compose logs -f beat

# Arranca el receptor de prueba con el secreto de un endpoint:
#   make receiver secret=whsec_...
#   make receiver secret=whsec_... status=500   (responde siempre 500)
receiver:
	WEBHOOK_SECRET='$(secret)' RECEIVER_STATUS='$(status)' docker compose --profile dev up --build receiver

test: .env
	docker compose run --rm api pytest

# Contra PostgreSQL real, en una base aparte (<POSTGRES_DB>_test) que se crea y se borra.
test-integration: .env
	docker compose run --rm api pytest -m integration

psql:
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# Crea una aplicación con su API key:
#   make create-app name="Mi tienda"
create-app: .env
	docker compose run --rm api python -m relay.entrypoints.create_app "$(name)"

# Aplica las migraciones pendientes.
migrate: .env
	docker compose run --rm api alembic upgrade head

# Genera una migración comparando los modelos con la base de datos:
#   make migration m="descripcion del cambio"
migration: .env
	docker compose run --rm api alembic revision --autogenerate -m "$(m)"
