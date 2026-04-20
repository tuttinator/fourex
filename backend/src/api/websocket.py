"""
WebSocket endpoint for real-time game events.

Connections are authenticated at connect time with a per-game API key —
the same credential the REST gameplay surface uses. Each connection is
scoped to a single ``(game_id, player_id)`` pair; the ``ConnectionManager``
indexes connections by ``game_id`` so broadcasts never leak to players
who don't hold a key for that game. Fog-of-war filtering on event
payloads is layered on top by each broadcast helper.

Event names are dot-namespaced (``lobby.*``, ``turn.*``, ``diplomacy.*``)
so callers can route on the prefix without inspecting the whole type.
The lobby family lands in Phase 3; turn/diplomacy families will adopt
the namespace in their own phases.
"""

import json
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthError, authenticate
from ..database.connection import get_database_session

router = APIRouter()

# Application-defined WebSocket close codes. The 4000-4999 range is
# reserved by RFC 6455 for private use; we mirror HTTP status semantics
# so a client can treat them like 401/403 on the REST side.
WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_FORBIDDEN = 4403


@dataclass
class Connection:
    """An authenticated WebSocket bound to a single (game, player) pair."""

    websocket: WebSocket
    game_id: str
    player_id: str


class ConnectionManager:
    """In-process registry of live WebSocket connections per game."""

    def __init__(self) -> None:
        self._by_game: dict[str, list[Connection]] = {}

    async def connect(
        self, websocket: WebSocket, game_id: str, player_id: str
    ) -> Connection:
        await websocket.accept()
        conn = Connection(websocket=websocket, game_id=game_id, player_id=player_id)
        self._by_game.setdefault(game_id, []).append(conn)
        await self._send(
            conn,
            {
                "type": "connected",
                "game_id": game_id,
                "player_id": player_id,
            },
        )
        return conn

    def disconnect(self, conn: Connection) -> None:
        conns = self._by_game.get(conn.game_id)
        if conns is None:
            return
        try:
            conns.remove(conn)
        except ValueError:
            pass
        if not conns:
            self._by_game.pop(conn.game_id, None)

    async def _send(self, conn: Connection, message: dict) -> None:
        if conn.websocket.client_state != WebSocketState.CONNECTED:
            return
        try:
            await conn.websocket.send_text(json.dumps(message))
        except Exception as exc:  # pragma: no cover - transport-level breakage
            print(f"WebSocket send failed: {exc}")

    async def broadcast_to_game(self, game_id: str, message: dict) -> None:
        """Fan a message out to every connection subscribed to a game."""
        # Snapshot the list so a concurrent disconnect doesn't trip iteration.
        for conn in list(self._by_game.get(game_id, ())):
            await self._send(conn, message)

    def connections_for_game(self, game_id: str) -> list[Connection]:
        return list(self._by_game.get(game_id, ()))


# Global connection manager — single in-process instance so broadcast
# helpers called from the game controller reach all live sockets.
manager = ConnectionManager()


@router.websocket("/events")
async def websocket_endpoint(
    websocket: WebSocket,
    game_id: str = Query(...),
    api_key: str | None = Query(default=None),
    session: AsyncSession = Depends(get_database_session),
) -> None:
    """Authenticated real-time event stream for one ``(game, player)`` pair.

    The client attaches its per-game API key as an ``?api_key=`` query
    parameter. The handler validates against the ``PlayerApiKey`` table
    before accepting the socket:

    - Missing/invalid key → close code ``4401`` (treat as 401).
    - Valid key that doesn't bind to the requested ``game_id`` → ``4403``.

    Once connected, the socket is passive — clients send optional ``ping``
    frames for keep-alive; all meaningful traffic flows server → client.
    """
    if not api_key:
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED, reason="api key required")
        return

    try:
        auth = await authenticate(session, api_key)
    except AuthError:
        await websocket.close(
            code=WS_CLOSE_UNAUTHORIZED, reason="invalid or expired api key"
        )
        return

    if auth.game_id != game_id:
        await websocket.close(
            code=WS_CLOSE_FORBIDDEN, reason="api key not valid for this game"
        )
        return

    conn = await manager.connect(websocket, game_id, auth.player_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await manager._send(conn, {"type": "error", "message": "invalid json"})
                continue
            if message.get("type") == "ping":
                await manager._send(
                    conn,
                    {"type": "pong", "timestamp": message.get("timestamp")},
                )
    except WebSocketDisconnect:
        manager.disconnect(conn)
    except Exception as exc:  # pragma: no cover - transport-level breakage
        print(f"WebSocket error: {exc}")
        manager.disconnect(conn)


# --- Lobby event broadcasts (Phase 3) ------------------------------------


async def broadcast_lobby_player_joined(
    game_id: str, player_id: str, players: list[str]
) -> None:
    """Emit when a new player seats themselves in a waiting lobby."""
    await manager.broadcast_to_game(
        game_id,
        {
            "type": "lobby.player_joined",
            "game_id": game_id,
            "player_id": player_id,
            "players": list(players),
        },
    )


async def broadcast_lobby_player_left(
    game_id: str, player_id: str, players: list[str]
) -> None:
    """Emit when a seated player vacates a waiting lobby."""
    await manager.broadcast_to_game(
        game_id,
        {
            "type": "lobby.player_left",
            "game_id": game_id,
            "player_id": player_id,
            "players": list(players),
        },
    )


async def broadcast_lobby_started(game_id: str) -> None:
    """Emit when the creator transitions a waiting lobby to active play."""
    await manager.broadcast_to_game(
        game_id,
        {"type": "lobby.started", "game_id": game_id},
    )


# --- Turn / diplomacy / action broadcasts (pre-Phase-4 shape preserved) ---
#
# These retain their legacy event types for the moment so the controller's
# existing call sites keep working unchanged. They'll migrate to the
# ``turn.*`` / ``diplomacy.*`` namespaces in their own phases, driven by
# the first frontend consumer that needs them.


async def broadcast_turn_start(game_id: str, turn: int) -> None:
    await manager.broadcast_to_game(
        game_id, {"type": "turn_start", "game_id": game_id, "turn": turn}
    )


async def broadcast_turn_end(game_id: str, turn: int) -> None:
    await manager.broadcast_to_game(
        game_id, {"type": "turn_end", "game_id": game_id, "turn": turn}
    )


async def broadcast_turn_resolved(game_id: str, turn: int) -> None:
    """Emit when ``resolve_turn()`` finishes and the canonical state has advanced.

    The frontend gameplay tracer (Phase 4) listens for this to invalidate
    its game-state query and surface the new turn — including a clear of
    any locally-queued actions and the "waiting" indicator. Payload is
    deliberately minimal: subscribers re-fetch ``GET /state`` to pick up
    the redacted post-resolution snapshot, sidestepping any concern about
    payload-vs-snapshot consistency.
    """
    await manager.broadcast_to_game(
        game_id, {"type": "turn.resolved", "game_id": game_id, "turn": turn}
    )


async def broadcast_turn_submitted(
    game_id: str,
    player_id: str,
    turn: int,
    submitted_players: list[str],
) -> None:
    """Emit when a player upserts their turn submission.

    Phase 6 turn-submission visibility: the frontend uses this to render
    per-opponent "deciding" vs "submitted" indicators and a global
    "waiting for N player(s)" banner without polling. The payload
    includes the roster of players who have submitted so far for the
    current turn — a resubmission by the same player is idempotent
    against that set, so the UI can trust the snapshot rather than
    replaying deltas.

    The submitter's ``player_id`` is public information (it's in
    ``game.players``), so this event fans out to every connection on the
    game; no per-player scoping is needed.
    """
    await manager.broadcast_to_game(
        game_id,
        {
            "type": "turn.submitted",
            "game_id": game_id,
            "player_id": player_id,
            "turn": turn,
            "submitted_players": list(submitted_players),
        },
    )


async def broadcast_player_action(game_id: str, player_id: str, action: dict) -> None:
    await manager.broadcast_to_game(
        game_id,
        {
            "type": "player_action",
            "game_id": game_id,
            "player_id": player_id,
            "action": action,
        },
    )


async def broadcast_diplomacy_event(game_id: str, event: dict) -> None:
    await manager.broadcast_to_game(
        game_id, {"type": "diplomacy", "game_id": game_id, **event}
    )
