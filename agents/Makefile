# Makefile for 4X AI Agents

.PHONY: help install test quick classic showcase advanced clean logs dev-install format lint type-check

help:
	@echo "4X AI Agents - Available Commands:"
	@echo ""
	@echo "Setup:"
	@echo "  install     - Install Python dependencies with uv"
	@echo "  dev-install - Install development dependencies with uv"
	@echo ""
	@echo "Game Commands:"
	@echo "  test        - Run test suite"
	@echo "  quick       - Run quick test game (2 players, 30 turns)"
	@echo "  classic     - Run classic 3-player game"
	@echo "  showcase    - Run personality showcase (4 players)"
	@echo "  advanced    - Run advanced strategies game"
	@echo "  interactive - Run interactive game setup"
	@echo ""
	@echo "Development:"
	@echo "  format      - Format code with black"
	@echo "  lint        - Lint code with flake8"
	@echo "  type-check  - Type check with mypy"
	@echo ""
	@echo "Utilities:"
	@echo "  clean       - Clean up log files"
	@echo "  logs        - Show recent game logs"
	@echo ""
	@echo "Configuration:"
	@echo "  Game Backend: http://localhost:8000"
	@echo "  LLM Backend:  http://localhost:1234"
	@echo "  Model:        qwen/qwen3-32b"

install:
	cd .. && uv sync --dev
	@echo "Dependencies installed!"

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

clean:
	rm -rf logs/*.json
	@echo "Log files cleaned!"

logs:
	@echo "Recent game logs:"
	@ls -la logs/ | head -10 || echo "No logs found"

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