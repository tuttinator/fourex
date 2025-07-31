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
agents-quick: ## Run a quick test game with agents
	cd agents && uv run python run_agents.py --preset quick_test

agents-classic: ## Run classic 3-player game
	cd agents && uv run python run_agents.py --preset classic_3p

agents-showcase: ## Run personality showcase (4 players)
	cd agents && uv run python run_agents.py --preset personality_showcase

agents-advanced: ## Run advanced strategies game
	cd agents && uv run python run_agents.py --preset advanced_strategies

agents-interactive: ## Run interactive game setup
	cd agents && uv run python run_agents.py --interactive

agents-test: ## Test agent functionality
	cd agents && uv run python test_agents.py

agents-mcp-server: ## Run MCP server for tool use
	cd agents && uv run python run_fastmcp_server.py

agents-logs: ## Show recent agent game logs
	@echo "Recent agent game logs:"
	@ls -la agents/logs/ | head -10 || echo "No agent logs found"

agents-clean: ## Clean up agent log files
	rm -rf agents/logs/*.json agents/test_logs/
	@echo "Agent log files cleaned!"

agents-analyze: ## Analyze agent player performance (usage: make agents-analyze PLAYER=<name>)
	cd agents && uv run python -c "from src.enhanced_logging import enhanced_logger; import sys; player = sys.argv[1] if len(sys.argv) > 1 else 'Alice'; print(enhanced_logger.analyze_player_performance(player))" $(if $(PLAYER),$(PLAYER),Alice)