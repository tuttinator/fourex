"""
Phase 5 — gameplay-improvements: multi-turn queued orders.

Covers the new ``QueueOrderAction`` / ``CancelOrderAction`` pair, the
turn-start resume phase, and all three cancellation ladders:
newly-visible enemy, obstructed next step, and "attacked last turn".
Also exercises queue persistence through a JSON round-trip and replay
determinism via ``resolve_turn``.
"""

from copy import deepcopy

from backend.src.game.models import (
    UNIT_STATS,
    AttackAction,
    CancelOrderAction,
    Coord,
    GameState,
    OrderCancellationReason,
    QueuedMoveOrder,
    QueueOrderAction,
    ResourceBag,
    Terrain,
    Tile,
    Unit,
    UnitType,
)
from backend.src.game.rules import (
    execute_cancel_order,
    execute_queue_order,
    redact_state,
    resolve_turn,
    resume_queued_orders,
)


def _plains_state(
    width: int = 10, height: int = 10, players: tuple[str, ...] = ("p1", "p2")
) -> GameState:
    state = GameState(map_width=width, map_height=height)
    tile_id = 0
    for y in range(height):
        for x in range(width):
            state.tiles.append(
                Tile(id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.GRASS)
            )
            tile_id += 1
    for p in players:
        state.players.append(p)
        state.stockpiles[p] = ResourceBag()
    return state


def _add_unit(
    state: GameState,
    x: int,
    y: int,
    owner: str = "p1",
    unit_type: UnitType = UnitType.SCOUT,
    moves_left: int | None = None,
) -> Unit:
    stats = UNIT_STATS[unit_type]
    unit = Unit(
        id=state.next_unit_id,
        owner=owner,
        type=unit_type,
        hp=stats.hp,
        moves_left=moves_left if moves_left is not None else stats.moves,
        loc=Coord(x=x, y=y),
    )
    state.units[unit.id] = unit
    state.next_unit_id += 1
    tile = state.get_tile(unit.loc)
    assert tile is not None
    tile.unit_ids.append(unit.id)
    return unit


class TestQueueOrderValidation:
    def test_queue_succeeds_on_reachable_tile(self) -> None:
        state = _plains_state()
        unit = _add_unit(state, 0, 0)
        action = QueueOrderAction(unit_id=unit.id, destination=Coord(x=5, y=5))

        result = execute_queue_order(state, "p1", action)

        assert result.success, result.message
        assert len(unit.orders_queue) == 1
        head = unit.orders_queue[0]
        assert isinstance(head, QueuedMoveOrder)
        assert head.destination == Coord(x=5, y=5)

    def test_queue_rejects_impassable_destination(self) -> None:
        state = _plains_state()
        target = state.get_tile(Coord(x=3, y=3))
        assert target is not None
        target.terrain = Terrain.MOUNTAIN
        unit = _add_unit(state, 0, 0)

        result = execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=3, y=3))
        )

        assert not result.success
        assert unit.orders_queue == []

    def test_queue_rejects_wrong_owner(self) -> None:
        state = _plains_state()
        unit = _add_unit(state, 0, 0, owner="p1")
        result = execute_queue_order(
            state, "p2", QueueOrderAction(unit_id=unit.id, destination=Coord(x=2, y=2))
        )
        assert not result.success

    def test_queue_rejects_current_tile(self) -> None:
        state = _plains_state()
        unit = _add_unit(state, 0, 0)
        result = execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=0, y=0))
        )
        assert not result.success

    def test_cancel_order_clears_queue(self) -> None:
        state = _plains_state()
        unit = _add_unit(state, 0, 0)
        execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=4, y=4))
        )
        assert unit.orders_queue

        execute_cancel_order(state, "p1", CancelOrderAction(unit_id=unit.id))

        assert unit.orders_queue == []


class TestResumeAdvance:
    def test_multi_turn_completion(self) -> None:
        """A scout with moves=3 should reach a destination 6 tiles away in two turns."""
        state = _plains_state()
        unit = _add_unit(state, 0, 0, unit_type=UnitType.SCOUT)
        execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=6, y=0))
        )
        assert unit.moves_left == 3

        state.turn = 1
        unit.moves_left = unit.stats.moves  # simulate reset_unit_moves
        resume_queued_orders(state)
        assert unit.loc == Coord(x=3, y=0)
        assert unit.orders_queue  # not yet complete

        state.turn = 2
        unit.moves_left = unit.stats.moves
        resume_queued_orders(state)
        assert unit.loc == Coord(x=6, y=0)
        assert unit.orders_queue == []
        completion_events = [e for e in state.order_events if e.unit_id == unit.id]
        assert any(
            e.reason == OrderCancellationReason.COMPLETED for e in completion_events
        )

    def test_cancel_on_attacked_last_turn(self) -> None:
        state = _plains_state()
        unit = _add_unit(state, 0, 0)
        execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=5, y=0))
        )
        unit.took_damage_last_turn = True
        unit.moves_left = unit.stats.moves

        state.turn = 1
        resume_queued_orders(state)

        assert unit.orders_queue == []
        assert unit.took_damage_last_turn is False
        assert any(
            e.reason == OrderCancellationReason.ATTACKED for e in state.order_events
        )
        # Unit did not move on a cancellation
        assert unit.loc == Coord(x=0, y=0)

    def test_cancel_on_newly_visible_enemy(self) -> None:
        state = _plains_state()
        unit = _add_unit(state, 0, 0, owner="p1", unit_type=UnitType.SCOUT)
        execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=6, y=0))
        )
        # After queue, add an enemy within the unit's new-position sight.
        _add_unit(state, 4, 0, owner="p2", unit_type=UnitType.SCOUT)

        state.turn = 1
        unit.moves_left = unit.stats.moves
        resume_queued_orders(state)

        assert unit.orders_queue == []
        assert any(
            e.reason == OrderCancellationReason.ENEMY_SIGHTED
            for e in state.order_events
        )

    def test_known_enemies_do_not_cancel(self) -> None:
        state = _plains_state()
        _add_unit(state, 3, 0, owner="p2", unit_type=UnitType.SCOUT)
        unit = _add_unit(state, 0, 0, owner="p1", unit_type=UnitType.SCOUT)
        # Enemy already in sight at queue time. Destination is behind
        # the enemy but the route passes through so known_enemy_ids
        # records the id and the order should still resume.
        execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=0, y=4))
        )
        assert unit.orders_queue
        head = unit.orders_queue[0]
        assert isinstance(head, QueuedMoveOrder)
        assert head.known_enemy_ids  # enemy captured at queue time

        state.turn = 1
        unit.moves_left = unit.stats.moves
        resume_queued_orders(state)

        # Unit moved at least one step and the order wasn't cancelled
        # because the visible enemy is one we already knew about.
        assert unit.loc != Coord(x=0, y=0)
        assert not any(
            e.reason == OrderCancellationReason.ENEMY_SIGHTED
            for e in state.order_events
        )

    def test_cancel_on_obstruction(self) -> None:
        state = _plains_state()
        unit = _add_unit(state, 0, 0, unit_type=UnitType.SCOUT)
        execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=5, y=0))
        )
        # Drop a mountain across the path after the order was queued.
        for x in range(state.map_width):
            for y in range(state.map_height):
                if x == 1 and y == 0:
                    state.get_tile(Coord(x=1, y=0)).terrain = Terrain.MOUNTAIN  # type: ignore[union-attr]
        # Also block the detour around (y=1) so there is no path at all.
        for x in range(state.map_width):
            state.get_tile(Coord(x=x, y=1)).terrain = Terrain.MOUNTAIN  # type: ignore[union-attr]

        state.turn = 1
        unit.moves_left = unit.stats.moves
        resume_queued_orders(state)

        assert unit.orders_queue == []
        assert any(
            e.reason == OrderCancellationReason.OBSTRUCTED for e in state.order_events
        )


class TestResolveTurnIntegration:
    def test_attacked_flag_cancels_next_turn(self) -> None:
        """Full resolve_turn loop: attack sets flag, next turn's resume cancels.

        Queue is submitted via action in the same turn the defender is
        attacked so that resume doesn't race ahead of the attack. On the
        next turn's resume the flag is read and cleared.
        """
        state = _plains_state()
        attacker = _add_unit(state, 0, 0, owner="p2", unit_type=UnitType.SOLDIER)
        defender = _add_unit(state, 1, 0, owner="p1", unit_type=UnitType.SOLDIER)

        # Turn 1: p1 queues an order and p2 attacks the still-stationary
        # defender. Resume runs first with no queue to advance, so the
        # attack lands; then the queue is set by action; then the turn
        # ends with defender.took_damage_last_turn = True.
        resolve_turn(
            state,
            {
                "p1": [
                    QueueOrderAction(
                        unit_id=defender.id, destination=Coord(x=5, y=0)
                    )
                ],
                "p2": [
                    AttackAction(
                        attacker_id=attacker.id,
                        target_id=defender.id,
                        target_type="unit",
                    )
                ],
            },
        )
        assert defender.id in state.units
        assert state.units[defender.id].took_damage_last_turn is True
        assert state.units[defender.id].orders_queue

        # Turn 2: resume sees the flag, cancels, clears it.
        resolve_turn(state, {"p1": [], "p2": []})
        assert state.units[defender.id].orders_queue == []
        assert state.units[defender.id].took_damage_last_turn is False
        assert any(
            e.reason == OrderCancellationReason.ATTACKED for e in state.order_events
        )

    def test_replay_determinism(self) -> None:
        """Same seed + same actions => identical hashes including order events."""

        def run() -> GameState:
            s = _plains_state()
            unit = _add_unit(s, 0, 0, owner="p1", unit_type=UnitType.SCOUT)
            execute_queue_order(
                s,
                "p1",
                QueueOrderAction(
                    unit_id=unit.id, destination=Coord(x=6, y=0)
                ),
            )
            for _ in range(3):
                resolve_turn(s, {"p1": [], "p2": []})
            return s

        a = run()
        b = run()
        assert a.hash_state() == b.hash_state()

    def test_queue_persistence_round_trip(self) -> None:
        """orders_queue survives a JSON round-trip (database persistence)."""
        state = _plains_state()
        unit = _add_unit(state, 0, 0)
        execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=4, y=0))
        )
        raw = state.model_dump(mode="json")
        rehydrated = GameState.model_validate(raw)

        u = rehydrated.get_unit(unit.id)
        assert u is not None
        assert len(u.orders_queue) == 1
        head = u.orders_queue[0]
        assert isinstance(head, QueuedMoveOrder)
        assert head.destination == Coord(x=4, y=0)


class TestRedaction:
    def test_enemy_orders_hidden_from_observer(self) -> None:
        state = _plains_state()
        state.discovered = {"p1": ["p2"], "p2": ["p1"]}
        _add_unit(state, 0, 0, owner="p1", unit_type=UnitType.SCOUT)
        enemy = _add_unit(state, 1, 0, owner="p2", unit_type=UnitType.SCOUT)
        execute_queue_order(
            state,
            "p2",
            QueueOrderAction(unit_id=enemy.id, destination=Coord(x=4, y=0)),
        )
        assert state.units[enemy.id].orders_queue

        redacted = redact_state(state, "p1")
        # Enemy unit is visible (adjacent) but the queue must be scrubbed.
        assert enemy.id in redacted.units
        assert redacted.units[enemy.id].orders_queue == []

    def test_own_orders_preserved(self) -> None:
        state = _plains_state()
        unit = _add_unit(state, 0, 0, owner="p1")
        execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=4, y=0))
        )
        redacted = redact_state(state, "p1")
        assert len(redacted.units[unit.id].orders_queue) == 1

    def test_events_scoped_to_owner(self) -> None:
        state = _plains_state()
        u1 = _add_unit(state, 0, 0, owner="p1")
        u2 = _add_unit(state, 5, 5, owner="p2")
        execute_queue_order(
            state, "p1", QueueOrderAction(unit_id=u1.id, destination=Coord(x=4, y=0))
        )
        execute_queue_order(
            state, "p2", QueueOrderAction(unit_id=u2.id, destination=Coord(x=5, y=9))
        )
        u1.took_damage_last_turn = True
        u2.took_damage_last_turn = True
        state.turn = 1
        u1.moves_left = u1.stats.moves
        u2.moves_left = u2.stats.moves
        resume_queued_orders(state)
        assert len(state.order_events) == 2

        r1 = redact_state(state, "p1")
        assert all(e.owner == "p1" for e in r1.order_events)
        r2 = redact_state(state, "p2")
        assert all(e.owner == "p2" for e in r2.order_events)


class TestLegacyStatesDeserialise:
    def test_legacy_unit_without_orders_queue(self) -> None:
        raw = {
            "id": 1,
            "owner": "p1",
            "type": "scout",
            "hp": 2,
            "moves_left": 3,
            "loc": {"x": 0, "y": 0},
        }
        u = Unit.model_validate(raw)
        assert u.orders_queue == []
        assert u.took_damage_last_turn is False


def test_deep_copy_preserves_orders() -> None:
    state = _plains_state()
    unit = _add_unit(state, 0, 0)
    execute_queue_order(
        state, "p1", QueueOrderAction(unit_id=unit.id, destination=Coord(x=5, y=0))
    )
    clone = deepcopy(state)
    assert len(clone.units[unit.id].orders_queue) == 1
