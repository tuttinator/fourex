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
db-init: ## Create database tables
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

mcp-server: ## Run MCP server for tool use (run in separate terminal from dev server)
	cd agents && uv run python run_fastmcp_server.py

run-all: ## Run both dev server and MCP server concurrently (requires background terminal support)
	@echo "Starting development services..."
	@echo "Note: This will run both services in the background. Use 'make stop-all' to stop them."
	nohup make run-dev > logs/dev-server.log 2>&1 & echo $$! > .dev-server.pid
	@sleep 3  # Wait for dev server to start
	nohup make mcp-server > logs/mcp-server.log 2>&1 & echo $$! > .mcp-server.pid
	@echo "Services started! Check logs/dev-server.log and logs/mcp-server.log for output"
	@echo "Dev server: http://localhost:8000"
	@echo "Run 'make stop-all' to stop all services"

stop-all: ## Stop all background services
	@echo "Stopping all services..."
	@if [ -f .dev-server.pid ]; then \
		kill `cat .dev-server.pid` 2>/dev/null || true; \
		rm -f .dev-server.pid; \
		echo "Dev server stopped"; \
	fi
	@if [ -f .mcp-server.pid ]; then \
		kill `cat .mcp-server.pid` 2>/dev/null || true; \
		rm -f .mcp-server.pid; \
		echo "MCP server stopped"; \
	fi
	@echo "All services stopped"

status: ## Check status of running services
	@echo "Service status:"
	@if [ -f .dev-server.pid ] && ps -p `cat .dev-server.pid` > /dev/null 2>&1; then \
		echo "✓ Dev server running (PID: `cat .dev-server.pid`)"; \
	else \
		echo "✗ Dev server not running"; \
	fi
	@if [ -f .mcp-server.pid ] && ps -p `cat .mcp-server.pid` > /dev/null 2>&1; then \
		echo "✓ MCP server running (PID: `cat .mcp-server.pid`)"; \
	else \
		echo "✗ MCP server not running"; \
	fi

# Modal deployment tasks
modal-deploy: ## Deploy Modal Ollama server for LLM support
	uv run modal deploy agents/deploy/modal_ollama.py

modal-logs: ## Show Modal app logs (usage: make modal-logs APP=ollama-server)
	uv run modal app logs $(if $(APP),$(APP),ollama-server)

modal-setup-env: ## Create agents/.env with Modal configuration
	@echo "Setting up agents/.env with Modal configuration..."
	@PROFILE=$$(uv run modal profile current 2>/dev/null); \
	if [ -z "$$PROFILE" ]; then \
		echo "Error: Could not get Modal profile. Make sure you're logged in with 'modal auth'"; \
		exit 1; \
	fi; \
	MODAL_URL="https://$$PROFILE--ollama-server-ollamaserver-serve.modal.run"; \
	echo "Found Modal URL: $$MODAL_URL"; \
	cp agents/.env.example agents/.env; \
	sed -i.bak "s|MODAL_OLLAMA_URL=.*|MODAL_OLLAMA_URL=$$MODAL_URL/v1|g" agents/.env; \
	sed -i.bak "s|MODAL_OLLAMA_MODEL=.*|MODAL_OLLAMA_MODEL=qwen3:32b|g" agents/.env; \
	sed -i.bak "s|PRIMARY_LLM_PROVIDER=.*|PRIMARY_LLM_PROVIDER=modal_ollama|g" agents/.env; \
	rm -f agents/.env.bak; \
	echo "agents/.env configured with Modal Ollama settings"; \
	echo "MODAL_OLLAMA_URL=$$MODAL_URL/v1"

modal-test: ## Test the Modal Ollama endpoint
	@echo "Testing Modal Ollama endpoint..."
	@if [ ! -f agents/.env ]; then \
		echo "Error: agents/.env not found. Run 'make modal-setup-env' first."; \
		exit 1; \
	fi; \
	cd agents && uv run python test_modal.py

agents-logs: ## Show recent agent game logs
	@echo "Recent agent game logs:"
	@ls -la agents/logs/ | head -10 || echo "No agent logs found"

agents-clean: ## Clean up agent log files
	rm -rf agents/logs/*.json agents/test_logs/
	@echo "Agent log files cleaned!"

agents-analyze: ## Analyze agent player performance (usage: make agents-analyze PLAYER=<name>)
	cd agents && uv run python -c "from src.enhanced_logging import enhanced_logger; import sys; player = sys.argv[1] if len(sys.argv) > 1 else 'Alice'; print(enhanced_logger.analyze_player_performance(player))" $(if $(PLAYER),$(PLAYER),Alice)