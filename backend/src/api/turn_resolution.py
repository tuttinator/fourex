"""Shared turn-resolution logic used by both REST and MCP submission paths.

Both ``PersistentGameController.submit_player_actions`` (REST) and the MCP
``submit_actions`` tool write to the ``turn_actions`` table via
``GameRepository.upsert_turn_action`` and then call
``check_and_resolve_turn`` here. This module is the single source of truth
for turn advancement: it reads the submitted set from ``turn_actions``,
decides whether the turn is complete (all submitted or timed out),
resolves it via ``rules.resolve_turn``, persists snapshots, updates the
game row, emits WebSocket broadcasts, and checks victory.

Lifting this out of ``mcp_server/tools/gameplay.py`` closes the bug where
REST submissions wrote to ``player_actions`` + an in-memory gate and
never advanced the turn in the canonical ``turn_actions``-driven flow.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update as sa_update

from ..database.models import Game as GameModel
from ..database.repository import GameRepository
from ..game.models import (
    Action,
    AttackAction,
    BuildBuildingAction,
    BuildImprovementAction,
    CancelTreatyAction,
    DeclareWarAction,
    FoundCityAction,
    GameState,
    MoveAction,
    ProposeTreatyAction,
    RespondToTreatyAction,
    SendMessageAction,
    TrainUnitAction,
    WithdrawTreatyAction,
)
from ..game.rules import redact_state, resolve_turn
from .websocket import (
    broadcast_diplomacy_message_received,
    broadcast_player_action,
    broadcast_turn_end,
    broadcast_turn_resolved,
    broadcast_turn_start,
)

# Turn timeout: 10 minutes.
TURN_TIMEOUT_SECONDS = 600


def parse_action(raw: dict[str, Any]) -> Action:
    """Parse a raw action dict (as stored in ``turn_actions.actions_json``) into a typed Action."""
    action_type = raw.get("type", "")
    if action_type == "MOVE":
        return MoveAction.model_validate(raw)
    elif action_type == "ATTACK":
        return AttackAction.model_validate(raw)
    elif action_type == "FOUND_CITY":
        return FoundCityAction.model_validate(raw)
    elif action_type == "TRAIN_UNIT":
        return TrainUnitAction.model_validate(raw)
    elif action_type == "BUILD_IMPROVEMENT":
        return BuildImprovementAction.model_validate(raw)
    elif action_type == "BUILD_BUILDING":
        return BuildBuildingAction.model_validate(raw)
    elif action_type == "DECLARE_WAR":
        return DeclareWarAction.model_validate(raw)
    elif action_type == "SEND_MESSAGE":
        return SendMessageAction.model_validate(raw)
    elif action_type == "PROPOSE_TREATY":
        return ProposeTreatyAction.model_validate(raw)
    elif action_type == "RESPOND_TO_TREATY":
        return RespondToTreatyAction.model_validate(raw)
    elif action_type == "WITHDRAW_TREATY":
        return WithdrawTreatyAction.model_validate(raw)
    elif action_type == "CANCEL_TREATY":
        return CancelTreatyAction.model_validate(raw)
    else:
        raise ValueError(f"Unknown action type: {action_type}")


async def check_and_resolve_turn(
    repo: GameRepository, game_id: str
) -> dict[str, Any] | None:
    """If the current turn is complete, resolve it and advance.

    A turn is complete when every player in ``game.players`` has an entry
    in ``turn_actions`` for ``state.turn``, or when the turn timeout has
    elapsed (players without submissions get an empty action list).

    Returns a summary dict when the turn was resolved, or ``None`` when
    we are still waiting.
    """
    game = await repo.get_game(game_id)
    if game is None:
        return None

    state = GameState.model_validate(game.state)
    current_turn = state.turn

    submitted = await repo.get_all_turn_actions(game_id, current_turn)
    submitted_players = {ta.player_id for ta in submitted}

    all_submitted = len(game.players) > 0 and set(game.players) == submitted_players

    timed_out = False
    if not all_submitted and game.turn_started_at:
        now = datetime.now(UTC).replace(tzinfo=None)
        elapsed = (now - game.turn_started_at).total_seconds()
        if elapsed >= TURN_TIMEOUT_SECONDS:
            timed_out = True

    if not all_submitted and not timed_out:
        return None

    player_actions: dict[str, list[Action]] = {}
    for player in game.players:
        ta = next((t for t in submitted if t.player_id == player), None)
        if ta and ta.actions_json:
            raw_list = ta.actions_json if isinstance(ta.actions_json, list) else []
            player_actions[player] = [parse_action(a) for a in raw_list]
        else:
            player_actions[player] = []

    await broadcast_turn_start(game_id, current_turn)
    for player_id, actions in player_actions.items():
        for action in actions:
            await broadcast_player_action(
                game_id,
                player_id,
                {
                    "type": action.type,
                    "unit_id": getattr(action, "unit_id", None),
                    "target_location": getattr(action, "target_location", None),
                    "player": player_id,
                },
            )

    # Snapshot the existing message IDs so we can diff which ones the
    # resolver appended and fan them out to sender+recipient only (Phase 7).
    existing_message_ids = {m.id for m in state.messages}

    turn_result = resolve_turn(state, player_actions)

    for player in game.players:
        redacted = redact_state(state, player)
        await repo.upsert_turn_snapshot(
            game_id=game_id,
            player_id=player,
            turn_number=current_turn,
            state_json=redacted.model_dump(mode="json"),
        )

    if state.turn % 10 == 0:
        await repo.create_game_snapshot(
            game_id=game_id,
            turn_number=state.turn,
            state=state,
            snapshot_type="periodic",
        )

    await repo.save_turn_result(game_id, turn_result, player_actions)
    await repo.update_game_state(game_id, state)

    await repo.session.execute(
        sa_update(GameModel)
        .where(GameModel.id == game_id)
        .values(turn_started_at=datetime.now(UTC).replace(tzinfo=None))
    )

    await broadcast_turn_end(game_id, state.turn)
    await broadcast_turn_resolved(game_id, state.turn)

    # Phase 7: emit one ``diplomacy.message_received`` per message the
    # resolver accepted this turn. Scoped to sender+recipient only so the
    # event stream honours message privacy (see ``redact_state``). Fired
    # after ``turn.resolved`` so clients that refetch the diplomacy state
    # on ``turn.resolved`` still pick up the per-event unread-badge
    # deltas — the order is "authoritative state refresh first, then
    # per-message signals".
    for message in state.messages:
        if message.id in existing_message_ids:
            continue
        await broadcast_diplomacy_message_received(
            game_id,
            {
                "id": message.id,
                "sender": message.sender,
                "recipient": message.recipient,
                "body": message.body,
                "turn_sent": message.turn_sent,
            },
            visible_to=(message.sender, message.recipient),
        )

    # Game-end check: match the MCP-path behaviour — only score-by-max-turns
    # triggers here. Domination / economic / elimination victory detection
    # (``rules.check_victory``) is intentionally not called from the shared
    # resolver: it fires too eagerly (e.g. turn 1 when only one player has
    # founded a city) and the MCP self-play suite relied on games
    # continuing past that point. Re-enabling early-victory detection needs
    # to be a deliberate follow-up, not a side-effect of this refactor.
    if state.turn >= game.max_turns:
        await repo.end_game(game_id, victory_type="score")
        await repo.create_game_snapshot(
            game_id=game_id,
            turn_number=state.turn,
            state=state,
            snapshot_type="final",
        )

    return {
        "turn_resolved": current_turn,
        "new_turn": state.turn,
        "timed_out": timed_out,
        "skipped_players": [p for p in game.players if p not in submitted_players],
    }
