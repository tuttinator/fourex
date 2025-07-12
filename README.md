# 4X Game Backend

A deterministic, turn-based strategy sandbox for AI agents research.

## Features

- **Deterministic gameplay**: Same seed + same actions = identical outcomes
- **REST API**: `/state`, `/actions`, `/prompts` endpoints with Bearer auth
- **Fog-of-war**: Players only see tiles within unit/city sight range
- **4X mechanics**: Explore, Expand, Exploit, Exterminate on 20x20 grid
- **Full test coverage**: 100% unit test coverage for core game logic

## Quick Start

```bash
# Install dependencies
make install

# Run tests
make test

# Start development server
make run-dev

# Run CLI demo with 4 players for 10 turns
make run-cli
```

## Game Mechanics

- **Map**: 20×20 grid with 4 terrain types (plains, forest, mountain, water)
- **Units**: Scout, Worker, Soldier, Archer with different stats
- **Cities**: Produce resources, train units, build improvements
- **Resources**: Food, Wood, Ore, Crystal for economy
- **Victory**: Domination (last player with cities) or Score (after 100 turns)

## API Usage

```bash
# Create game
curl -X POST "http://localhost:8000/api/v1/games/test/start" \
  -H "Authorization: Bearer player_alice" \
  -H "Content-Type: application/json" \
  -d '{"players": ["alice", "bob"], "seed": 42}'

# Get game state (with fog-of-war)
curl "http://localhost:8000/api/v1/state?game_id=test" \
  -H "Authorization: Bearer player_alice"

# Submit actions
curl -X POST "http://localhost:8000/api/v1/actions?game_id=test" \
  -H "Authorization: Bearer player_alice" \
  -H "Content-Type: application/json" \
  -d '[{"type": "MOVE", "unit_id": 1, "to": {"x": 5, "y": 6}}]'
```

## Development

```bash
# Format code
make format

# Run linting
make lint

# Run tests with coverage
make test-cov

# Start with Docker Compose
docker-compose up -d postgres redis
make run-dev
```

## Architecture

```txt
backend/
├── src/
│   ├── game/           # Pure game logic (deterministic)
│   │   ├── models.py   # Pydantic data models
│   │   ├── rules.py    # Turn resolution, combat, economy
│   │   └── __main__.py # CLI testing tool
│   ├── api/            # FastAPI endpoints
│   │   ├── rest.py     # REST endpoints
│   │   └── game_controller.py # Game state management
│   ├── config.py       # Settings
│   └── main.py         # ASGI app
└── tests/              # 100% test coverage
    ├── test_models.py
    ├── test_rules.py
    └── test_api.py
```
