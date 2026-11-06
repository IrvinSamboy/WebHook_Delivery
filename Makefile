.PHONY: up down logs test psql migrate migration create-app

.env:
	cp .env.example .env

up: .env
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

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
