# 4X Arena Frontend

A Next.js 15 research dashboard for observing and analyzing AI agents playing 4X strategy games.

## Features

- **Real-time Game Observation**: Live WebSocket updates from ongoing matches
- **Historical Replay**: Turn-by-turn replay with timeline scrubbing
- **Fog-of-War Visualization**: Toggle per-player visibility
- **LLM Prompt Inspection**: View agent reasoning and token usage
- **Diff Mode**: Highlight changes between turns
- **Research Analytics**: Combat events, diplomacy tracking, resource monitoring

## Tech Stack

- **Next.js 15** with App Router
- **React 19** with TypeScript
- **Tailwind CSS** + shadcn/ui components
- **Zustand** for state management
- **TanStack Query** for data fetching
- **WebSocket** native API for real-time updates
- **Konva** for map canvas rendering

## Development

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Type checking
npm run type-check

# Run tests
npm test
```

## Environment Variables

Create a `.env.local` file:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

## Project Structure

```txt
src/
├── app/                    # Next.js 15 App Router
│   ├── games/             # Game lobby and observation
│   │   └── [id]/
│   │       ├── observe/   # Live match view
│   │       └── replay/    # Historical replay
│   └── admin/             # Admin panel
├── components/            # React components
│   ├── ui/               # shadcn/ui components
│   ├── map-canvas.tsx    # Game map visualization
│   ├── player-list.tsx   # Player sidebar
│   └── event-log.tsx     # Real-time event stream
├── hooks/                # Custom React hooks
├── lib/                  # Utilities and API client
├── store/                # Zustand stores
└── types/                # TypeScript definitions
```

## Key Components

### MapCanvas

Interactive game map with:

- Tile-based terrain rendering
- Unit and city visualization
- Click handlers for inspection
- Hover tooltips
- Fog-of-war overlay

### PlayerList

Per-player information:

- Resource stockpiles
- Unit and city counts
- Diplomatic relationships
- Visibility toggle

### GameStore

Centralized state management:

- WebSocket connection handling
- Turn-based game state caching
- Real-time updates
- Historical snapshot loading

## API Integration

The frontend connects to the 4X game backend via:

- **REST API**: `/state`, `/actions`, `/prompts` endpoints
- **WebSocket**: Real-time event stream at `/events`
- **Bearer Authentication**: Simple token-based auth

## Usage

1. **Game Lobby**: Browse active and finished games
2. **Live Observation**: Watch AI agents play in real-time
3. **Historical Replay**: Analyze past games turn-by-turn
4. **Admin Panel**: Manage games and view system metrics

## Research Features

- **Prompt Inspection**: View LLM reasoning for each turn
- **Token Analytics**: Track usage and latency metrics
- **State Diffing**: Visualize changes between turns
- **Event Timeline**: Combat, diplomacy, and economic events
- **Deterministic Replay**: Exact game state reproduction

## Performance

- **Bundle Size**: <250KB gzipped critical path
- **Cold Load**: <2s to first painted map
- **WebSocket Latency**: <200ms event to UI update
- **Timeline Seek**: <400ms turn navigation

## Accessibility

- Keyboard navigation support
- ARIA live regions for events
- High contrast color schemes
- Screen reader compatibility
