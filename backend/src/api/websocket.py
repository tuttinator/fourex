"""
WebSocket endpoints for real-time game events.
"""

import json

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState


router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections for real-time game updates."""

    def __init__(self):
        # Store connections by game_id -> list of websockets
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, game_id: str):
        """Accept a WebSocket connection and add it to the game room."""
        await websocket.accept()

        if game_id not in self.active_connections:
            self.active_connections[game_id] = []

        self.active_connections[game_id].append(websocket)

        # Send connection confirmation
        await self.send_personal_message(
            {"type": "connected", "status": "connected", "game_id": game_id}, websocket
        )

    def disconnect(self, websocket: WebSocket, game_id: str):
        """Remove a WebSocket connection from the game room."""
        if game_id in self.active_connections:
            if websocket in self.active_connections[game_id]:
                self.active_connections[game_id].remove(websocket)

            # Clean up empty game rooms
            if not self.active_connections[game_id]:
                del self.active_connections[game_id]

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific WebSocket connection."""
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                print(f"Error sending message: {e}")

    async def broadcast_to_game(self, message: dict, game_id: str):
        """Send a message to all connections watching a specific game."""
        if game_id not in self.active_connections:
            return

        # Create a copy of the list to avoid modification during iteration
        connections = self.active_connections[game_id].copy()

        for connection in connections:
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_text(json.dumps(message))
            except Exception as e:
                print(f"Error broadcasting to connection: {e}")
                # Remove broken connection
                self.disconnect(connection, game_id)


# Global connection manager instance
manager = ConnectionManager()


@router.websocket("/events")
async def websocket_endpoint(
    websocket: WebSocket,
    game_id: str = Query(...),
):
    """
    WebSocket endpoint for real-time game events.

    Clients can connect to receive live updates about:
    - Turn changes
    - Game state updates
    - Player actions
    - Diplomacy events
    """
    await manager.connect(websocket, game_id)

    try:
        # Send initial game info without game validation for now
        await manager.send_personal_message(
            {
                "type": "game_info",
                "game_id": game_id,
                "message": "Connected to game events",
            },
            websocket,
        )

        # Keep the connection alive and handle incoming messages
        while True:
            try:
                # Wait for messages from client (for now, just keep alive)
                data = await websocket.receive_text()
                message = json.loads(data)

                # Handle client messages if needed
                if message.get("type") == "ping":
                    await manager.send_personal_message(
                        {"type": "pong", "timestamp": message.get("timestamp")},
                        websocket,
                    )

            except json.JSONDecodeError:
                await manager.send_personal_message(
                    {"type": "error", "message": "Invalid JSON"}, websocket
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket, game_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket, game_id)


# Utility functions for broadcasting events (to be used by game logic)
async def broadcast_turn_start(game_id: str, turn: int):
    """Broadcast turn start event to all watchers of a game."""
    await manager.broadcast_to_game(
        {"type": "turn_start", "game_id": game_id, "turn": turn}, game_id
    )


async def broadcast_turn_end(game_id: str, turn: int):
    """Broadcast turn end event to all watchers of a game."""
    await manager.broadcast_to_game(
        {"type": "turn_end", "game_id": game_id, "turn": turn}, game_id
    )


async def broadcast_player_action(game_id: str, player_id: str, action: dict):
    """Broadcast player action to all watchers of a game."""
    await manager.broadcast_to_game(
        {
            "type": "player_action",
            "game_id": game_id,
            "player_id": player_id,
            "action": action,
        },
        game_id,
    )


async def broadcast_diplomacy_event(game_id: str, event: dict):
    """Broadcast diplomacy event to all watchers of a game."""
    await manager.broadcast_to_game(
        {"type": "diplomacy", "game_id": game_id, **event}, game_id
    )
