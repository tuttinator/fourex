# Makefile for 4X AI Agents

.PHONY: help install test quick classic showcase advanced clean logs dev-install format lint type-check

help:
	@echo "4X AI Agents - Available Commands:"
	@echo ""
	@echo "Setup:"
	@echo "  install     - Install Python dependencies with uv"
	@echo "  dev-install - Install development dependencies with uv"
	@echo "  setup-env   - Copy .env.example to .env for configuration"
	@echo ""
	@echo "Game Commands:"
	@echo "  test        - Run comprehensive test suite"
	@echo "  quick       - Run quick test game (2 players, 30 turns)"
	@echo "  classic     - Run classic 3-player game"
	@echo "  showcase    - Run personality showcase (4 players)"
	@echo "  advanced    - Run advanced strategies game"
	@echo "  interactive - Run interactive game setup"
	@echo ""
	@echo "MCP Server:"
	@echo "  mcp-server  - Run MCP server for tool use"
	@echo ""
	@echo "Development:"
	@echo "  format      - Format code with black"
	@echo "  lint        - Lint code with flake8"
	@echo "  type-check  - Type check with mypy"
	@echo ""
	@echo "Utilities:"
	@echo "  clean       - Clean up log files"
	@echo "  logs        - Show recent game logs"
	@echo "  analyze     - Analyze player performance from logs"
	@echo ""
	@echo "Configuration:"
	@echo "  Game Backend: http://localhost:8000"
	@echo "  LLM Backend:  https://your-modal-endpoint-url/v1 (default, cloud)"
	@echo "                or http://localhost:1234 (optional, local LLM Studio)"
	@echo "  Model:        qwen3:32b (Modal) or qwen/qwen3-32b (LLM Studio)"
	@echo "  Providers:    Modal (default), LLM Studio (optional), OpenAI (fallback)"
	@echo ""
	@echo "  To deploy Modal Ollama, see agents/deploy/modal_ollama.py."

install:
	cd .. && uv sync --dev
	@echo "Dependencies installed!"

setup-env:
	cp .env.example .env
	@echo "Environment file created! Please edit .env with your API keys."

test:
	uv run python test_agents.py

quick:
	uv run python run_agents.py --preset quick_test

classic:
	uv run python run_agents.py --preset classic_3p

showcase:
	uv run python run_agents.py --preset personality_showcase

advanced:
	uv run python run_agents.py --preset advanced_strategies

interactive:
	uv run python run_agents.py --interactive

mcp-server:
	uv run python run_mcp_server.py

clean:
	rm -rf logs/*.json test_logs/
	@echo "Log files cleaned!"

logs:
	@echo "Recent game logs:"
	@ls -la logs/ | head -10 || echo "No logs found"

analyze:
	@echo "Player performance analysis:"
	uv run python -c "from src.enhanced_logging import enhanced_logger; import sys; player = sys.argv[1] if len(sys.argv) > 1 else 'Alice'; print(enhanced_logger.analyze_player_performance(player))" $(if $(PLAYER),$(PLAYER),Alice)

# Development targets
dev-install:
	uv sync --dev
	@echo "Development dependencies installed with uv!"

format:
	uv run black src/ *.py

lint:
	uv run flake8 src/ *.py

type-check:
	uv run mypy src/ --ignore-missing-imports

# Custom game configurations
custom-aggressive:
	uv run python run_agents.py --players "Warrior" "Berserker" "Conqueror" \
	                     --personalities aggressive aggressive aggressive \
	                     --max-turns 75 --game-id all_aggressive

custom-economic:
	uv run python run_agents.py --players "Trader" "Builder" "Industrialist" \
	                     --personalities economic economic economic \
	                     --max-turns 100 --game-id all_economic

custom-mixed:
	uv run python run_agents.py --players "Alpha" "Beta" "Gamma" "Delta" "Epsilon" \
	                     --personalities aggressive defensive explorer economic diplomatic \
	                     --max-turns 150 --game-id five_player_mixed