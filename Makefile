COMPOSE = docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml

.PHONY: init check-env config up down logs status smoke db-upgrade db-status db-role db-connect db-test lint typecheck s3-init api ingestion-test ingestion-e2e discovery-test discovery-import discovery-run matching-import matching-dispatch matching-test matching-e2e matching-benchmark notification-import notification-test notification-e2e web-install web-dev web-lint web-typecheck web-build web-test web-e2e local-worker

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

discovery-test: check-env
	uv run --frozen --env-file .env python -m scripts.db_admin discovery-test-database
	uv run --frozen --env-file .env pytest tests/discovery

discovery-import: check-env
	docker cp workflows/discovery.json $$(docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml ps -q n8n):/tmp/discovery.json
	$(COMPOSE) exec -T n8n n8n import:workflow --input=/tmp/discovery.json

discovery-run: check-env
	@set -e; $(COMPOSE) stop n8n; trap '$(COMPOSE) up -d --wait --wait-timeout 180 n8n' EXIT; $(COMPOSE) run --rm --no-deps n8n execute --id=loanDiscoveryM4

matching-import: check-env
	docker cp workflows/matching.json $$(docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml ps -q n8n):/tmp/matching.json
	$(COMPOSE) exec -T n8n n8n import:workflow --input=/tmp/matching.json

matching-dispatch: check-env
	uv run --frozen --env-file .env python -m services.eligibility.dispatcher --once

matching-test: check-env
	uv run --frozen --env-file .env python -m scripts.db_admin matching-test-database
	uv run --frozen --env-file .env pytest tests/matching

matching-e2e: check-env
	uv run --frozen --env-file .env python -m scripts.matching_e2e

matching-benchmark: check-env
	uv run --frozen --env-file .env python -m benchmarks.eligibility.run

notification-import: check-env
	docker cp workflows/notifications.json $$(docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml ps -q n8n):/tmp/notifications.json
	$(COMPOSE) exec -T n8n n8n import:workflow --input=/tmp/notifications.json

notification-test: check-env
	uv run --frozen --env-file .env python -m scripts.db_admin notification-test-database
	uv run --frozen --env-file .env pytest tests/notifications

notification-e2e: check-env
	uv run --frozen --env-file .env python -m scripts.notification_e2e

local-worker: check-env
	uv run --frozen --env-file .env python -m scripts.local_ingestion_bridge --watch

web-install:
	npm ci --prefix apps/web --no-audit --no-fund

web-dev:
	npm run dev --prefix apps/web

web-lint:
	npm run lint --prefix apps/web

web-typecheck:
	npm run typecheck --prefix apps/web

web-build:
	npm run build --prefix apps/web

web-test:
	npm run test:unit --prefix apps/web

web-e2e:
	npm run test:e2e --prefix apps/web

lint:
	uv run --frozen ruff check apps services scripts tests benchmarks database/migrations

typecheck:
	uv run --frozen mypy
