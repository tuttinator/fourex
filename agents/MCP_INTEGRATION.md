# MCP Integration for 4X AI Agents

This document describes the Model Context Protocol (MCP) integration that provides agents with advanced game analysis tools for better strategic decision-making within the fog of war.

## Overview

The MCP integration allows AI agents to use sophisticated analysis tools to:

- **Analyze Territory**: Examine terrain and resources within visible areas
- **Evaluate Military Position**: Assess threats and tactical opportunities
- **Find Resource Opportunities**: Identify strategic resource locations
- **Validate Actions**: Check action validity before execution
- **Calculate Distances**: Optimize unit positioning and movement

## Architecture

### MCP Server (`src/mcp_server.py`)

- Runs game analysis tools accessible via MCP protocol
- Provides 6 core analysis tools for strategic planning
- Integrates with game backend for real-time state access

### MCP Client (`src/mcp_client.py`)

- Connects agents to MCP server for tool access
- Provides simplified interface for comprehensive analysis
- Handles data formatting and error recovery

### Agent Integration (`src/agent.py`)

- Each agent automatically initializes MCP client
- Runs comprehensive analysis before each turn planning
- Integrates MCP results into LLM prompts for better decisions

## Available MCP Tools

### 1. `get_game_state`

```python
# Get current game state within fog of war
result = await mcp_client.get_game_state(game_id)
```

**Parameters:**

- `game_id`: Game identifier
- `player_id`: Player perspective for fog of war

**Returns:** Filtered game state visible to the player

### 2. `analyze_territory`

```python
# Analyze terrain around a location
result = await mcp_client.analyze_territory(
    game_id, center_x=10, center_y=15, radius=3
)
```

**Parameters:**

- `game_id`: Game identifier
- `player_id`: Analyzing player
- `center_x`, `center_y`: Analysis center coordinates
- `radius`: Analysis radius (default: 3)

**Returns:** Terrain analysis, resource assessment, threat evaluation

### 3. `evaluate_military_position`

```python
# Assess military threats and opportunities
result = await mcp_client.evaluate_military_position(game_id)
```

**Parameters:**

- `game_id`: Game identifier
- `player_id`: Player perspective

**Returns:** Military strength assessment, threat analysis, tactical recommendations

### 4. `find_resource_opportunities`

```python
# Identify strategic resource locations
result = await mcp_client.find_resource_opportunities(game_id)
```

**Parameters:**

- `game_id`: Game identifier
- `player_id`: Player perspective

**Returns:** Resource location analysis, expansion opportunities, economic strategy

### 5. `validate_actions`

```python
# Validate potential actions before execution
result = await mcp_client.validate_actions(game_id, actions)
```

**Parameters:**

- `game_id`: Game identifier
- `player_id`: Player executing actions
- `actions`: List of proposed actions

**Returns:** Action validity, success probability, alternative suggestions

### 6. `calculate_distances`

```python
# Calculate strategic distances
result = await mcp_client.calculate_distances(
    game_id, from_coords, to_coords
)
```

**Parameters:**

- `game_id`: Game identifier
- `player_id`: Player perspective
- `from_coords`: List of source coordinates
- `to_coords`: List of target coordinates

**Returns:** Distance matrix, movement planning, positioning analysis

## Agent Planning Integration

### Comprehensive Analysis

Each agent automatically runs comprehensive MCP analysis before planning:

```python
# Automatic MCP analysis in agent.play_turn()
if self.mcp_client.is_available():
    mcp_analysis = await self.mcp_client.comprehensive_analysis(
        game_id, game_state
    )
```

### LLM Prompt Enhancement

MCP analysis results are integrated into LLM prompts:

```
ADVANCED STRATEGIC ANALYSIS (via MCP tools):

Military Assessment:
- Current military strength: Strong
- Visible threats: Enemy archer at (12,8)
- Tactical opportunities: Flanking position available

Resource Opportunities:
- Crystal node at (15,10) - uncontested
- Food resources depleted in current area
- Expansion south recommended

Territory Analysis:
- Area 1 (Unit 3) at (10,12): Defensive terrain, good visibility
- Area 2 (City 1) at (8,15): Resource rich, needs protection

Strategic Distances:
- Units to cities: Average 4 moves
- Units to threats: Minimum 2 moves
- Expansion targets: 6-8 moves

Use this MCP analysis to guide your strategic decisions.
```

## Usage Examples

### Basic MCP Integration

```python
from src.mcp_client import MCPGameClient

# Initialize MCP client
mcp_client = MCPGameClient("player_alice")

# Check availability
if mcp_client.is_available():
    # Run comprehensive analysis
    analysis = await mcp_client.comprehensive_analysis(
        game_id="test_game", game_state=current_state
    )

    # Use analysis for decision making
    if analysis.get("military", {}).get("threats"):
        # Respond to military threats
        pass
```

### Agent with MCP Enhancement

```python
from src.agent import FourXAgent

# Agents automatically initialize MCP client
agent = FourXAgent("player_alice", "aggressive")

# MCP analysis runs automatically during turn planning
success = await agent.play_turn("test_game")
```

## Configuration

### Environment Variables

```env
# MCP Server Configuration
MCP_SERVER_PORT=3000

# Enable/disable MCP integration
USE_PERSISTENT_GAME_CLIENT=true
```

### Agent Configuration

```python
# MCP integration is enabled by default
agent = FourXAgent(
    player_id="alice",
    personality="aggressive",
    use_persistent_client=True  # Enables MCP integration
)
```

## Benefits for AI Agents

### Enhanced Strategic Awareness

- **Fog of War Intelligence**: Better understanding of visible game state
- **Threat Assessment**: Early detection of military risks
- **Resource Planning**: Optimal expansion and economic strategy

### Improved Decision Quality

- **Validated Actions**: Reduced invalid moves and failed strategies
- **Tactical Positioning**: Optimized unit placement and movement
- **Long-term Planning**: Strategic distance calculations for expansion

### Personality-Driven Strategy

- **Aggressive Players**: Focus on military threat analysis and attack opportunities
- **Economic Players**: Emphasize resource opportunities and expansion planning
- **Defensive Players**: Prioritize threat detection and territorial analysis

## Performance Impact

### Analysis Overhead

- **Comprehensive Analysis**: ~100-200ms per turn
- **Individual Tools**: ~10-50ms per call
- **Caching**: Results cached within turn for efficiency

### LLM Enhancement

- **Prompt Quality**: Significantly improved strategic context
- **Decision Accuracy**: Better action selection within fog of war
- **Token Usage**: Moderate increase (~200-500 tokens per turn)

## Testing

Run MCP integration tests:

```bash
# Test MCP server components
python test_agents.py

# Specific MCP tests
python -c "
from src.mcp_client import MCPGameClient
client = MCPGameClient('test')
print(f'MCP available: {client.is_available()}')
"

# Test agent integration
python -c "
from src.agent import FourXAgent
agent = FourXAgent('test', 'balanced')
print(f'Agent MCP ready: {agent.mcp_client.is_available()}')
"
```

## Debugging

### Enable MCP Logging

```python
import structlog

# Enable debug logging for MCP components
logger = structlog.get_logger()
logger.debug("MCP analysis result", analysis=mcp_analysis)
```

### MCP Analysis Inspection

```python
# Inspect MCP analysis results
analysis = await mcp_client.comprehensive_analysis(game_id, state)
print(f"Military threats: {analysis.get('military', {})}")
print(f"Resource opportunities: {analysis.get('resources', {})}")
print(f"Territory count: {len(analysis.get('territory_analyses', []))}")
```

## Troubleshooting

### Common Issues

1. **MCP Server Not Available**

   ```
   Error: MCP server not available
   Solution: Check MCP server initialization in mcp_client.py
   ```

2. **Analysis Timeouts**

   ```
   Error: MCP tool call timeout
   Solution: Increase timeout or check game backend connectivity
   ```

3. **Invalid Analysis Results**

   ```
   Error: JSON decode error in MCP response
   Solution: Check MCP tool response format and error handling
   ```

### Debugging Steps

1. **Check MCP Client Status**

   ```python
   print(f"MCP available: {agent.mcp_client.is_available()}")
   ```

2. **Test Individual Tools**

   ```python
   result = await mcp_client.get_game_state(game_id)
   print(f"Game state result: {result}")
   ```

3. **Validate Analysis Results**

   ```python
   analysis = await mcp_client.comprehensive_analysis(game_id, state)
   print(f"Analysis keys: {list(analysis.keys())}")
   ```

## Future Enhancements

Planned improvements:

- **Real-time MCP Protocol**: Full MCP standard implementation
- **Custom Tool Development**: Game-specific analysis tools
- **Performance Optimization**: Parallel tool execution
- **Advanced Caching**: Cross-turn analysis persistence
- **Tool Composition**: Chained analysis workflows
