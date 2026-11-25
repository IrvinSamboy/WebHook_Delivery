.PHONY: up down logs worker-logs beat-logs receiver test test-integration lint format check psql migrate migration create-app load load-report

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
#   make receiver secret=whsec_... delay=2      (tarda 2 s en responder)
receiver:
	WEBHOOK_SECRET='$(secret)' RECEIVER_STATUS='$(status)' RECEIVER_DELAY='$(delay)' docker compose --profile dev up --build receiver

test: .env
	docker compose run --rm api pytest

# Contra PostgreSQL real, en una base aparte (<POSTGRES_DB>_test) que se crea y se borra.
test-integration: .env
	docker compose run --rm api pytest -m integration

# Estilo, errores comunes y tipos: lo mismo que comprueba el CI.
lint: .env
	docker compose run --rm --no-deps api sh -c 'ruff check . && ruff format --check . && mypy'

# Ordena imports y formatea el código.
format: .env
	docker compose run --rm --no-deps api sh -c 'ruff check --fix . && ruff format .'

# Todo lo del CI: lint + unitarios + integración.
check: lint test test-integration

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

# Prueba de carga con Locust (ver backend/loadtests/locustfile.py):
#   make load                         50 usuarios durante 60 s
#   make load users=200 duration=2m
#   make load delay=2                 el receptor tarda 2 s en responder
# Deja la API en modo carga (4 procesos, sin --reload); make up la devuelve a desarrollo.
LOAD_COMPOSE = docker compose -f docker-compose.yml -f docker-compose.load.yml
load: .env
	RECEIVER_DELAY='$(delay)' $(LOAD_COMPOSE) --profile dev up -d --build api worker beat receiver
	mkdir -p backend/loadtests/results
	@key=$$($(LOAD_COMPOSE) run --rm api python -m relay.entrypoints.create_app loadtest | sed -n 's/^API key: *//p'); \
	RELAY_API_KEY=$$key LOAD_USERS='$(or $(users),50)' LOAD_DURATION='$(or $(duration),60s)' \
		$(LOAD_COMPOSE) --profile load run --rm locust

# Latencia de extremo a extremo de la última prueba de carga.
load-report: .env
	docker compose run --rm api python loadtests/report.py
