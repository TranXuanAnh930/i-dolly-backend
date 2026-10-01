# Shortcuts for the commands in README.md "Getting started". Docker-backed
# targets run inside the compose `app` service; lint/compile run on the host.
.DEFAULT_GOAL := help

COMPOSE ?= docker compose
APP     ?= app
EXEC    := $(COMPOSE) exec $(APP)

.PHONY: help env install-dev up up-d build down stop restart logs ps shell \
        migrate migration downgrade seed seed-ja test cov lint lint-fix compile check clean

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# --- Setup -------------------------------------------------------------------
env: ## Create .env from .env.example (won't overwrite an existing one)
	@test -f .env && echo ".env already exists" || (cp .env.example .env && echo "Created .env — fill in the secrets")

install-dev: ## Install app + dev dependencies (ruff) on the host
	pip install -r requirements-dev.txt

# --- Stack -------------------------------------------------------------------
up: ## Build and start app, Postgres, Redis and the Celery worker (foreground)
	$(COMPOSE) up --build

up-d: ## Same as `up`, detached
	$(COMPOSE) up --build -d

build: ## Rebuild images without starting
	$(COMPOSE) build

stop: ## Stop containers, keeping database data
	$(COMPOSE) stop

down: ## Remove containers (named volumes, i.e. DB data, are kept)
	$(COMPOSE) down

restart: ## Restart app and worker (e.g. after changing a Celery task)
	$(COMPOSE) restart $(APP) worker

logs: ## Follow logs; narrow with `make logs s=worker`
	$(COMPOSE) logs -f $(s)

ps: ## Show container status
	$(COMPOSE) ps

shell: ## Open a shell in the app container
	$(EXEC) sh

# --- Database ----------------------------------------------------------------
migrate: ## Apply all Alembic migrations
	$(EXEC) python -m alembic upgrade head

migration: ## Autogenerate a migration: make migration m="add foo table"
	@test -n "$(m)" || (echo 'usage: make migration m="message"' && exit 1)
	$(EXEC) python -m alembic revision --autogenerate -m "$(m)"

downgrade: ## Roll back one migration
	$(EXEC) python -m alembic downgrade -1

seed: ## Seed sample data (English) — idempotent
	$(EXEC) python scripts/seed.py

seed-ja: ## Seed sample data (Japanese) — use instead of `seed`, not both
	$(EXEC) python scripts/seed_ja.py

# --- Quality -----------------------------------------------------------------
test: ## Run the test suite in the app container; pass args with `make test a="-k lottery"`
	$(EXEC) pytest $(a)

cov: ## Run tests with coverage
	$(EXEC) pytest --cov=app --cov-report=term-missing $(a)

lint: ## Run ruff on the host (same check as CI)
	ruff check .

lint-fix: ## Run ruff with autofix
	ruff check . --fix

compile: ## py_compile sweep — static fallback when no DB is available
	python -m compileall -q app alembic scripts tests main.py

check: lint compile ## Lint + compile sweep (no DB/Redis needed)

clean: ## Remove caches and coverage output
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	rm -f .coverage coverage.xml
