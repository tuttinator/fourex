.PHONY: help install install-uv lint test test-cov run-dev clean sync

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
	uv run black --check src tests
	uv run ruff check src tests
	uv run mypy src

format: ## Format code
	uv run black src tests
	uv run ruff check --fix src tests

test: ## Run tests
	uv run pytest tests/

test-cov: ## Run tests with coverage
	uv run pytest --cov=src --cov-report=term-missing tests/

run-dev: ## Run development server
	uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

run-cli: ## Run CLI with random seed
	uv run python -m src.game --players 4 --turns 10 --seed 42

clean: ## Clean up temporary files
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .coverage .pytest_cache .mypy_cache