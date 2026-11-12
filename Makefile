.PHONY: up down logs worker-logs receiver test psql migrate migration create-app

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

# Arranca el receptor de prueba con el secreto de un endpoint:
#   make receiver secret=whsec_...
receiver:
	WEBHOOK_SECRET='$(secret)' docker compose --profile dev up --build receiver

test: .env
	docker compose run --rm api pytest

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
