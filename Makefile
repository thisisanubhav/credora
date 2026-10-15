COMPOSE = docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml

.PHONY: init check-env config up down logs status smoke

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
