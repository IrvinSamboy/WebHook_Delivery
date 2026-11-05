.PHONY: up down logs test psql migrate migration

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

# Aplica las migraciones pendientes.
migrate: .env
	docker compose run --rm api alembic upgrade head

# Genera una migración comparando los modelos con la base de datos:
#   make migration m="descripcion del cambio"
migration: .env
	docker compose run --rm api alembic revision --autogenerate -m "$(m)"
