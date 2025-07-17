# Database Persistence for 4X Game Backend

This document describes the database persistence feature that allows game data to survive server reloads and provides resilient game state management.

## Overview

The 4X game backend now includes comprehensive database persistence using PostgreSQL and SQLAlchemy. This enables:

- **Game State Persistence**: Complete game state is stored in the database
- **Server Restart Recovery**: Games can continue after server restarts
- **Turn History**: All turns and actions are logged
- **Game Snapshots**: Periodic backups of game state
- **Enhanced Logging**: Detailed LLM prompt/response logging with thinking tokens

## Database Schema

### Core Tables

- **`games`**: Main game instances with metadata
- **`game_turns`**: Turn-by-turn processing results
- **`player_actions`**: Individual player actions within turns
- **`prompt_logs`**: LLM interactions with enhanced metadata
- **`game_snapshots`**: Periodic complete state backups
- **`player_stats`**: Aggregated player performance metrics

### Key Features

- **Automatic Snapshots**: Every 10 turns for quick recovery
- **Turn Logging**: Complete action history with results
- **Performance Metrics**: Token usage and latency tracking
- **State Validation**: Hash-based integrity checking

## Setup Instructions

### 1. Package Manager Setup

The project uses `uv` for fast Python package management. Install it if you haven't already:

```bash
# Install uv package manager
make install-uv
# or manually:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install Dependencies

```bash
# Install all dependencies including dev tools
make install
# or:
uv sync --dev
```

### 3. Database Setup

```bash
# Install PostgreSQL (macOS with Homebrew)
brew install postgresql
brew services start postgresql

# Create database and user
createdb fourex
psql fourex -c "CREATE USER fourex WITH PASSWORD 'fourex';"
psql fourex -c "GRANT ALL PRIVILEGES ON DATABASE fourex TO fourex;"
```

### 4. Environment Configuration

Copy and configure the environment file:

```bash
cp backend/.env.example backend/.env
```

Edit `.env` with your database connection:

```env
DATABASE_URL=postgresql+asyncpg://fourex:fourex@localhost:5432/fourex
SQL_DEBUG=false
```

### 5. Initialize Database

```bash
# Create tables (from project root)
make db-create

# Or reset existing database
make db-reset

# Check database connection
make db-check
```

### 6. Start the Server

```bash
# Start backend development server (from project root)
make backend-dev

# Or start with hot reload
make run-dev
```

The server will automatically initialize the database on startup.

## Usage

### Game Management

```bash
# List all games (from project root)
make db-list

# Get detailed game info
make db-info GAME=<game_id>

# Check database connection
make db-check

# Database maintenance
make db-reset  # WARNING: Deletes all data
make db-create # Create fresh tables
```

### API Endpoints

New persistence-aware endpoints:

- `GET /api/v1/games/{game_id}/info` - Game metadata and status
- `POST /api/v1/games/{game_id}/restore` - Restore from snapshot
- `GET /api/v1/state` - Enhanced with persistence support
- `POST /api/v1/actions` - Automatically saved to database

### Agent Integration

Agents now automatically use persistent connections with `uv`:

```python
# Agents will automatically:
# 1. Check for existing games in database
# 2. Restore from snapshots if needed
# 3. Create new games if none exist
# 4. Handle server restarts gracefully

# Run with uv from project root
orchestrator = GameOrchestrator(config)
results = await orchestrator.run_game()  # Persistence automatic
```

### Running Tests

```bash
# Run backend tests with uv
make backend-test

# Run with coverage
make test-cov
```

## Recovery Scenarios

### Server Restart Recovery

1. **Automatic Detection**: Server checks for existing games on startup
2. **State Restoration**: Games are restored from latest snapshots
3. **Turn Continuation**: Play resumes from the last completed turn
4. **Action Recovery**: Pending actions are preserved

### Database Recovery

```bash
# Emergency database recovery (from project root)
make db-reset  # WARNING: Deletes all data
make db-create

# Restore from backup (if you have database backups)
pg_restore -d fourex backup_file.sql

# Check status after recovery
make db-check
```

### Game State Validation

The system includes automatic state validation:

- **Hash Verification**: Each turn generates a state hash
- **Snapshot Integrity**: Snapshots are validated on restore
- **Action Consistency**: Player actions are verified before processing

## Performance Considerations

### Database Optimization

- **Connection Pooling**: Async connection management
- **Indexed Queries**: Optimized database indexes
- **Batch Operations**: Efficient bulk inserts
- **Lazy Loading**: On-demand data retrieval

### Snapshot Strategy

- **Periodic Snapshots**: Every 10 turns (configurable)
- **Critical Snapshots**: Before major game events
- **Cleanup Policy**: Old snapshots are retained for history

## Monitoring and Logging

### Enhanced Logging

The system now captures:

- **LLM Interactions**: Full prompt/response with thinking tokens
- **Performance Metrics**: Token usage, latency, provider info
- **Turn Processing**: Detailed action execution logs
- **Error Recovery**: Automatic retry and fallback logging

### Database Monitoring

```bash
# Monitor database size with uv
uv run python -c "
import asyncio
from src.database.connection import get_engine
async def check_size():
    engine = await get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(\"SELECT pg_size_pretty(pg_database_size('fourex'))\")
        print(f'Database size: {result.fetchone()[0]}')
asyncio.run(check_size())
"

# Or use the simpler check command
make db-check
```

## Configuration Options

### Makefile Commands

The project includes convenient Makefile targets for common database operations:

```bash
# Package management
make install-uv      # Install uv package manager
make install         # Install all dependencies
make sync           # Sync dependencies from lock file

# Database operations
make db-create      # Create database tables
make db-drop        # Drop all tables (WARNING: deletes data!)
make db-reset       # Drop and recreate all tables
make db-check       # Check database connection
make db-list        # List all games
make db-info GAME=<game_id>  # Show game details

# Development
make backend-dev    # Run backend development server
make backend-test   # Run backend tests
make test-cov       # Run tests with coverage
make lint          # Run linting and type checking
make format        # Format code

# Show all available commands
make help
```

### Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:port/dbname
SQL_DEBUG=true  # Enable SQL query logging

# Persistence Features
USE_PERSISTENT_GAME_CLIENT=true
ENABLE_GAME_SNAPSHOTS=true
SNAPSHOT_INTERVAL=10  # Turns between snapshots

# Performance
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
```

### Game Configuration

```python
# Enable persistence in game configuration
config = GameConfig(
    game_id="persistent_game",
    players=["Alice", "Bob"],
    personalities={"Alice": "aggressive", "Bob": "defensive"},
    max_turns=100,
    # Persistence is automatic
)
```

## Troubleshooting

### Common Issues

1. **Database Connection Failed**

   ```bash
   # Check PostgreSQL is running
   brew services list | grep postgresql

   # Test connection from project root
   make db-check
   ```

2. **Game State Not Found**

   ```bash
   # Check if game exists in database
   make db-info GAME=<game_id>

   # List all games
   make db-list

   # Restore from snapshot
   curl -X POST "http://localhost:8000/api/v1/games/<game_id>/restore"
   ```

3. **Performance Issues**

   ```bash
   # Enable SQL debugging in .env file
   echo "SQL_DEBUG=true" >> backend/.env

   # Check database status
   make db-check
   ```

### Migration Issues

If you encounter migration problems:

```bash
# Reset and recreate (from project root)
make db-reset

# Manual migration (if using Alembic)
cd backend
uv run alembic upgrade head

# Or check current migration status
cd backend
uv run alembic current
```

## Security Considerations

- **Database Credentials**: Store in environment variables
- **Connection Encryption**: Use SSL in production
- **Access Control**: Limit database user permissions
- **Backup Strategy**: Regular database backups
- **Sensitive Data**: LLM prompts may contain game strategies

## Future Enhancements

Planned improvements:

- **Game Analytics**: Advanced performance metrics
- **Multi-Game Support**: Concurrent game management
- **Real-time Synchronization**: WebSocket state updates
- **Backup Automation**: Scheduled database backups
- **Game Replay**: Complete game history playback
