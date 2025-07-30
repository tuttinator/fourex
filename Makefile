.PHONY: help install install-uv lint test test-cov run-dev sync

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install-uv: ## Install uv package manager
	curl -LsSf https://astral.sh/uv/install.sh | sh

install: ## Install dependencies with uv
	uv sync --dev

sync: ## Sync dependencies (install/update based on lock file)
	uv sync --dev

lint: ## Run linting and type checking
	uv run black --check agents backend tests
	uv run ruff check agents backend tests
	uv run mypy agents backend

format: ## Format code
	uv run black agents backend tests
	uv run ruff check --fix agents backend tests

test: ## Run tests
	uv run pytest tests/

test-cov: ## Run tests with coverage
	uv run pytest --cov=src --cov-report=term-missing tests/

run-dev: ## Run development server
	uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

run-cli: ## Run CLI with random seed
	uv run python -m src.game --players 4 --turns 10 --seed 42

# Database management tasks
db-create: ## Create database tables
	cd backend && uv run python manage_db.py create

db-drop: ## Drop all database tables (WARNING: deletes all data!)
	cd backend && uv run python manage_db.py drop

db-reset: ## Drop and recreate all database tables
	cd backend && uv run python manage_db.py reset

db-check: ## Check database connection
	cd backend && uv run python manage_db.py check

db-list: ## List all games in database
	cd backend && uv run python manage_db.py list-games

db-info: ## Show detailed game info (usage: make db-info GAME=<game_id>)
	cd backend && uv run python manage_db.py game-info $(GAME)

# Backend development tasks
backend-dev: ## Run backend development server
	cd backend && uv run python src/main.py

backend-test: ## Run backend tests
	cd backend && uv run pytest tests/

# Agent tasks
quick: ## Run a quick test game with agents
	cd agents && uv run python run_agents.py --preset quick_test --auto-confirm

agents-test: ## Test agent functionality
	cd agents && uv run python test_agents.py