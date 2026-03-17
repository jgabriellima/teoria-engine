.PHONY: up down restart logs status health service unservice preflight build test test-up test-down test-smoke help

ENGINE := ./bin/teoria-engine
COMPOSE_TEST := docker compose -f docker-compose.yml -f docker-compose.test.yml --project-name teoria-test

up: ## Start all services
	@$(ENGINE) up

down: ## Stop all services
	@$(ENGINE) down

restart: ## Restart all services
	@$(ENGINE) restart

logs: ## Follow service logs
	@$(ENGINE) logs

status: ## Show container status
	@$(ENGINE) status

health: ## Check gateway health endpoint
	@$(ENGINE) health

service: ## Install as systemd service (requires sudo)
	@sudo $(ENGINE) service

unservice: ## Remove systemd service (requires sudo)
	@sudo $(ENGINE) unservice

preflight: ## Check system prerequisites
	@$(ENGINE) preflight

build: ## Rebuild gateway image without starting
	@docker compose -f docker-compose.yml build

test-up: ## Start test stack (mock vLLM, no GPU)
	@$(COMPOSE_TEST) up -d --build
	@echo "[test] waiting for services..."
	@for i in $$(seq 1 60); do \
		python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')" 2>/dev/null && break; \
		sleep 1; \
	done
	@echo "[test] stack ready"

test-down: ## Stop test stack
	@$(COMPOSE_TEST) down -v --remove-orphans

test: test-up ## Run integration + E2E tests against mock stack
	@TEST_NGINX_URL=http://localhost:8081 TEST_API_KEY=test-key-123 \
		uv run --with pytest --with httpx pytest tests/ -v --tb=short --ignore=tests/test_smoke.py; \
		code=$$?; $(COMPOSE_TEST) down -v --remove-orphans; exit $$code

test-smoke: ## Run smoke tests against REAL stack (requires GPU + make up)
	@uv run --with pytest --with httpx pytest tests/test_smoke.py -v --tb=long

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
