COMPOSE = docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml

.PHONY: init check-env config up down logs status smoke db-upgrade db-status db-role db-connect db-test lint typecheck s3-init api ingestion-test ingestion-e2e

init:
	python3 scripts/local_env.py init

check-env:
	python3 scripts/local_env.py check

config: check-env
	$(COMPOSE) config --quiet

up: config
	$(COMPOSE) up -d --wait --wait-timeout 180

down: check-env
	$(COMPOSE) down

logs: check-env
	$(COMPOSE) logs --tail=100 -f

status: check-env
	$(COMPOSE) ps

smoke: config
	python3 scripts/smoke_infrastructure.py

db-upgrade: check-env
	uv run --frozen --env-file .env alembic -c database/alembic.ini upgrade head

db-status: check-env
	uv run --frozen --env-file .env alembic -c database/alembic.ini current

db-role: check-env
	uv run --frozen --env-file .env python -m scripts.db_admin runtime-role

db-connect: check-env
	uv run --frozen --env-file .env python -m scripts.db_admin check

db-test: check-env
	uv run --frozen --env-file .env python -m scripts.db_admin test-database
	uv run --frozen --env-file .env pytest tests/integration tests/unit

s3-init: check-env
	uv run --frozen --env-file .env python -m scripts.local_s3 init

api: check-env
	uv run --frozen --env-file .env uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

ingestion-test: check-env
	uv run --frozen --env-file .env python -m scripts.db_admin ingestion-test-database
	uv run --frozen --env-file .env pytest tests/ingestion

ingestion-e2e: check-env
	uv run --frozen --env-file .env python -m scripts.ingestion_e2e

lint:
	uv run --frozen ruff check apps services scripts tests database/migrations

typecheck:
	uv run --frozen mypy
