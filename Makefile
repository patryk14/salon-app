# Day-to-day shortcuts. `make` without arguments prints help.
# Convention: a `## description` comment after the target name shows up in `make help`.

.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help up down logs test lint build clean

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

up: .env ## Build and start the whole environment (waits for healthchecks)
	$(COMPOSE) up -d --build --wait
	@echo ""
	@echo "  API      http://localhost:8000   (docs: /docs — outside prod only, health: /healthz, ready: /readyz)"
	@echo "  Web      http://localhost:4321"
	@echo "  MinIO    http://localhost:9001   (minio / minio12345)"
	@echo "  Mailpit  http://localhost:8025"

down: ## Stop containers (data in volumes is kept)
	$(COMPOSE) down --remove-orphans

logs: ## Follow logs of all services (Ctrl+C to exit)
	$(COMPOSE) logs -f --tail=100

test: ## Backend tests (locally via uv, not in the container — the prod image has no pytest)
	uv run --directory backend pytest

lint: ## Backend lint + format check (ruff)
	uv run --directory backend ruff check .
	uv run --directory backend ruff format --check .

build: ## Build the api image exactly the way CI will (no compose cache)
	docker build -t salon-api:local ./backend

clean: ## Remove containers, volumes (DB/MinIO/node_modules data!), the local image and build caches
	$(COMPOSE) down -v --remove-orphans --rmi local
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	rm -rf frontend/dist frontend/.astro

# .env is not in the repo; the first `make up` creates it from the example.
.env:
	cp .env.example .env
	@echo "Created .env from .env.example (local, non-secret values)."
