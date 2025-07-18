# 4X AI Agents

AI agents that play the 4X strategy game using Modal (cloud) or local LLM Studio integration.

## Features

- **Multiple Agent Personalities**: 8 different strategic personalities including aggressive, defensive, explorer, economic, diplomatic, balanced, tech-focused, and opportunist
- **LLM Integration**: Uses Modal (cloud, OpenAI-compatible) by default, with optional local LLM Studio fallback
- **Game Orchestration**: Manages multiple agents in a single game with turn-based coordination
- **Rich Logging**: Comprehensive game logs with agent decisions, timing, and outcomes
- **Flexible Configuration**: Command-line, interactive, or file-based configuration options

## Setup

1. Install dependencies:

```bash
cd .. && uv sync --dev
```

2. Make sure you have:
   - The game backend running at `http://localhost:8000`
   - **(Recommended)** Modal Ollama server deployed (see below)
   - **(Optional)** LLM Studio running at `http://localhost:1234` with a model loaded

3. Test the connection:

```bash
uv run python -c "from src.agent import FourXAgent; print('Agent setup successful!')"
```

## LLM Provider Options

### 1. Modal Ollama (Recommended, Cloud)

- Deploy the Modal Ollama server using the provided `agents/deploy/modal_ollama.py` script (see comments in that file for deployment instructions).
- Set the following in your `.env`:

```
MODAL_OLLAMA_URL=https://your-modal-endpoint-url/v1
MODAL_OLLAMA_MODEL=qwen3:32b
```

- The agents will use this endpoint by default for all LLM calls.

### 2. Local LLM Studio (Optional, Fallback)

- If `MODAL_OLLAMA_URL` is not set, the agents will use LLM Studio at `http://localhost:1234/v1` (or as configured in `.env`).
- Set the following in your `.env` if you want to override the default:

```
LLM_STUDIO_URL=http://localhost:1234/v1
LLM_STUDIO_MODEL=qwen/qwen3-32b
```

### 3. OpenAI (Fallback)

- If neither Modal nor LLM Studio is available, and you have an `OPENAI_API_KEY` set, the agents will use OpenAI's API as a fallback.

## Usage

### Quick Start

Run a quick test game with 2 players:

```bash
uv run python run_agents.py --preset quick_test
```

### Interactive Setup

Set up a custom game interactively:

```bash
uv run python run_agents.py --interactive
```

### Command Line Options

```bash
uv run python run_agents.py --players Alice Bob Charlie \
                     --personalities aggressive defensive economic \
                     --max-turns 100 \
                     --game-id my_game
```

### Using Configuration Files

Save a configuration:

```bash
uv run python run_agents.py --interactive --save-config my_config.json
```

Load a configuration:

```bash
uv run python run_agents.py --config my_config.json
```

### Available Presets

- `quick_test`: 2 players, 30 turns (aggressive vs defensive)
- `classic_3p`: 3 players, 75 turns (warrior, builder, trader)
- `personality_showcase`: 4 players, 100 turns (showcases different personalities)
- `advanced_strategies`: 4 players, 120 turns (advanced personalities)

## Agent Personalities

### Aggressive Conqueror

- Focuses on military expansion and direct confrontation
- Prioritizes building armies and attacking enemies
- Prefers war over diplomacy

### Defensive Strategist

- Builds strong defenses and steady economic development
- Avoids unnecessary conflicts
- Focuses on walls, granaries, and defensive positions

### Bold Explorer

- Prioritizes exploration and rapid territorial expansion
- Builds scouts and workers for quick expansion
- Claims valuable territories before others

### Economic Powerhouse

- Focuses on resource production and infrastructure
- Builds improvements on every valuable tile
- Maximizes long-term economic growth

### Master Diplomat

- Uses diplomacy and alliances to achieve victory
- Avoids military conflicts when possible
- Builds reputation as trustworthy partner

### Balanced Strategist

- Adapts strategy based on current situation
- Maintains balanced military, economic, and diplomatic capabilities
- Responds flexibly to threats and opportunities

### Technology Pioneer

- Focuses on crystal resources and advanced technology
- Builds the most advanced buildings available
- Uses technological superiority to dominate

### Cunning Opportunist

- Exploits weaknesses and takes advantage of opportunities
- Builds mobile forces for rapid response
- Switches between cooperation and competition as beneficial

## Configuration

### Game Configuration

```json
{
  "game_id": "my_game",
  "players": ["Alice", "Bob", "Charlie"],
  "personalities": {
    "Alice": "aggressive",
    "Bob": "defensive",
    "Charlie": "economic"
  },
  "max_turns": 100,
  "game_backend_url": "http://localhost:8000/api/v1",
  "llm_backend_url": "https://your-modal-endpoint-url/v1",
  "llm_model": "qwen3:32b"
}
```

### LLM Configuration

The agents use an OpenAI-compatible API. By default, this is the Modal Ollama endpoint if set, otherwise local LLM Studio, then OpenAI.

Example Modal Ollama request:

```bash
curl https://your-modal-endpoint-url/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:32b",
    "messages": [
      {"role": "system", "content": "You are a 4X strategy game AI..."},
      {"role": "user", "content": "Analyze the current game state..."}
    ],
    "temperature": 0.7,
    "max_tokens": 2000
  }'
```

Example LLM Studio request (optional):

```bash
curl http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen/qwen3-32b",
    "messages": [
      {"role": "system", "content": "You are a 4X strategy game AI..."},
      {"role": "user", "content": "Analyze the current game state..."}
    ],
    "temperature": 0.7,
    "max_tokens": 2000
  }'
```

## Game Logs

All games are logged to `logs/game_log_<game_id>_<timestamp>.json` with:

- Game configuration
- Turn-by-turn decisions for each agent
- Agent performance metrics (success rate, response time)
- Strategic analysis and reasoning for each action

## Troubleshooting

### Common Issues

1. **LLM Connection Failed**: Make sure LLM Studio is running and accessible
2. **Game Backend Connection Failed**: Make sure the game backend is running
3. **Model Not Found**: Check that the specified model is loaded in LLM Studio
4. **Structured Output Parsing Failed**: Some models may not support JSON mode properly

### Debug Mode

Add debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Testing Individual Components

Test the game client:

```python
# Run with uv
uv run python -c "from src.agent import GameClient; client = GameClient(); print('Game client OK')"
```

Test the LLM client:

```python
# Run with uv
uv run python -c "from src.agent import LLMClient; llm = LLMClient(); print('LLM client OK')"
```

## Architecture

- `src/agent.py`: Core agent implementation with game state parsing and action generation
- `src/orchestrator.py`: Game orchestration and multi-agent coordination
- `src/personalities.py`: Agent personality definitions and prompts
- `run_agents.py`: Main script for running games with various configuration options

## Development

### Adding New Personalities

1. Add a new personality configuration in `src/personalities.py`
2. Define the strategic priorities and system prompt
3. Test with a custom game configuration

### Extending Game Logic

1. Update the game state parsing in `GameClient._parse_game_state()`
2. Add new action types to the `ActionType` enum
3. Update the structured output models if needed
4. Modify the action conversion in `FourXAgent._convert_actions_to_api()`

### Custom LLM Integration

1. Create a new LLM client class inheriting from `LLMClient`
2. Implement the `generate_plan()` method
3. Update the orchestrator to use the new client
