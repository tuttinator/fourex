# 4X Game Backend

A deterministic, turn-based strategy sandbox for AI agents research.

## Features

- **Deterministic gameplay**: Same seed + same actions = identical outcomes
- **REST API**: `/state`, `/actions`, `/prompts` endpoints with Bearer auth
- **Fog-of-war**: Players only see tiles within unit/city sight range
- **4X mechanics**: Explore, Expand, Exploit, Exterminate on 20x20 grid
- **AI Agent Integration**: Complete system for multi-agent AI gameplay
- **MCP Server**: Model Context Protocol server for advanced game analysis
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

# Run MCP Server
make mcp-server

# Quick AI agent test game
make agents-quick

# Run interactive agent setup
make agents-interactive
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

## AI Agents

The project includes a complete AI agent system that allows multiple LLM-powered agents to play strategic games autonomously.

### Agent Features

- **8 Agent Personalities**: Aggressive, Defensive, Explorer, Economic, Diplomatic, Balanced, Tech-focused, and Opportunist
- **LLM Integration**: Uses Modal (cloud), local LLM Studio, or OpenAI
- **Game Orchestration**: Manages multi-agent games with turn coordination
- **MCP Integration**: Advanced game analysis tools via Model Context Protocol
- **Rich Logging**: Comprehensive decision logs and performance analytics

### Quick Agent Commands

```bash
# Quick 2-player test game (30 turns)
make agents-quick

# Classic 3-player game (75 turns)
make agents-classic

# Personality showcase (4 players, 100 turns)
make agents-showcase

# Advanced strategies game (4 players, 120 turns)
make agents-advanced

# Interactive game setup
make agents-interactive

# Test agent functionality
make agents-test

# View recent game logs
make agents-logs

# Clean up log files
make agents-clean

# Analyze player performance
make agents-analyze PLAYER=Alice
```

### LLM Provider Setup

#### 1. Modal Ollama (Recommended)

Deploy the Modal Ollama server and set in `.env`:

```env
MODAL_OLLAMA_URL=https://your-modal-endpoint-url/v1
MODAL_OLLAMA_MODEL=qwen3:32b
```

#### 2. Local LLM Studio (Optional)

Run LLM Studio locally and set in `.env`:

```env
LLM_STUDIO_URL=http://localhost:1234/v1
LLM_STUDIO_MODEL=qwen/qwen3-32b
```

#### 3. OpenAI (Fallback)

Set your OpenAI API key:

```env
OPENAI_API_KEY=your_api_key_here
```

### Agent Personalities

- **Aggressive Conqueror**: Military expansion and direct confrontation
- **Defensive Strategist**: Strong defenses and steady economic development
- **Bold Explorer**: Rapid territorial expansion and exploration
- **Economic Powerhouse**: Resource production and infrastructure focus
- **Master Diplomat**: Alliances and diplomatic victory paths
- **Balanced Strategist**: Adaptive strategy based on game state
- **Technology Pioneer**: Crystal resources and advanced technology
- **Opportunist**: Exploits weaknesses and adapts to circumstances

## MCP Server

The Model Context Protocol (MCP) server provides advanced game analysis tools that enhance AI agent decision-making within the fog of war.

### MCP Features

- **Territory Analysis**: Examine terrain and resources in visible areas
- **Military Assessment**: Evaluate threats and tactical opportunities
- **Resource Discovery**: Identify strategic resource locations
- **Action Validation**: Check action validity before execution
- **Distance Calculation**: Optimize unit positioning and movement
- **Comprehensive Analysis**: Full strategic situation assessment

### Running the MCP Server

```bash
# Start the MCP server
make agents-mcp-server
```

The server runs on `stdio` transport and provides 6 core analysis tools:

1. `get_game_state` - Current game state within fog of war
2. `analyze_territory` - Territory and resource analysis
3. `analyze_military_position` - Military threats and opportunities
4. `find_resource_opportunities` - Strategic resource locations
5. `validate_actions` - Action validity checking
6. `calculate_distances` - Movement and positioning optimization

### MCP Integration

Agents automatically use MCP tools for enhanced strategic analysis:

```python
# Agents automatically run comprehensive analysis
analysis = await agent.mcp_client.comprehensive_analysis(game_id, player_id)

# Results are integrated into LLM prompts for better decisions
strategic_context = analysis['territory_analysis']
military_assessment = analysis['military_position']
resource_opportunities = analysis['resource_opportunities']
```
