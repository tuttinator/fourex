"""
Gameplay-improvements Phase 6 — worker auto-improve automation.

Exercises the ``UnitAutomation.AUTO_IMPROVE`` mode: picking the nearest
unimproved own-territory tile, routing there across turns, building on
arrival, picking a new target, and the three cancellation ladders
(enemy adjacency, manual override, no reachable target). Also covers
legacy deserialisation (``automation`` defaults to ``None`` so pre-
Phase-6 persisted states still load) and replay determinism across
JSON round-trips.
"""

from copy import deepcopy

from backend.src.game.models import (
    UNIT_STATS,
    AutomationCancellationReason,
    ClearAutomationAction,
    Coord,
    GameState,
    ImprovementType,
    MoveAction,
    Resource,
    ResourceBag,
    SetAutomationAction,
    Terrain,
    Tile,
    Unit,
    UnitAutomation,
    UnitType,
)
from backend.src.game.rules import (
    execute_clear_automation,
    execute_set_automation,
    resolve_turn,
    resume_automation,
    resume_queued_orders,
)


def _owned_plains_state(
    width: int = 10,
    height: int = 10,
    players: tuple[str, ...] = ("p1", "p2"),
    owner: str = "p1",
) -> GameState:
    """Build a fully-owned plains map with no pre-existing improvements.

    Ownership covers the entire map so every plains tile is a potential
    auto-improve target without needing to set up cities / borders.
    """
    state = GameState(map_width=width, map_height=height)
    tile_id = 0
    for y in range(height):
        for x in range(width):
            state.tiles.append(
                Tile(
                    id=tile_id,
                    loc=Coord(x=x, y=y),
                    terrain=Terrain.GRASS,
                    owner=owner,
                )
            )
            tile_id += 1
    for p in players:
        state.players.append(p)
        state.stockpiles[p] = ResourceBag(food=100, wood=100, ore=100, crystal=100)
    return state


def _add_worker(state: GameState, x: int, y: int, owner: str = "p1") -> Unit:
    stats = UNIT_STATS[UnitType.WORKER]
    unit = Unit(
        id=state.next_unit_id,
        owner=owner,
        type=UnitType.WORKER,
        hp=stats.hp,
        moves_left=stats.moves,
        loc=Coord(x=x, y=y),
    )
    state.units[unit.id] = unit
    state.next_unit_id += 1
    tile = state.get_tile(unit.loc)
    assert tile is not None
    tile.unit_ids.append(unit.id)
    return unit


def _add_enemy(
    state: GameState,
    x: int,
    y: int,
    owner: str = "p2",
    unit_type: UnitType = UnitType.SOLDIER,
) -> Unit:
    stats = UNIT_STATS[unit_type]
    unit = Unit(
        id=state.next_unit_id,
        owner=owner,
        type=unit_type,
        hp=stats.hp,
        moves_left=stats.moves,
        loc=Coord(x=x, y=y),
    )
    state.units[unit.id] = unit
    state.next_unit_id += 1
    tile = state.get_tile(unit.loc)
    assert tile is not None
    tile.unit_ids.append(unit.id)
    return unit


def _set_food_resource(state: GameState, x: int, y: int) -> None:
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.resource = Resource.FOOD


class TestSetAutomationValidation:
    def test_set_auto_improve_on_worker(self) -> None:
        state = _owned_plains_state()
        worker = _add_worker(state, 0, 0)
        _set_food_resource(state, 2, 0)
        result = execute_set_automation(
            state,
            "p1",
            SetAutomationAction(
                unit_id=worker.id, mode=UnitAutomation.AUTO_IMPROVE
            ),
        )
        assert result.success, result.message
        assert worker.automation == UnitAutomation.AUTO_IMPROVE

    def test_rejects_non_worker(self) -> None:
        state = _owned_plains_state()
        stats = UNIT_STATS[UnitType.SCOUT]
        scout = Unit(
            id=state.next_unit_id,
            owner="p1",
            type=UnitType.SCOUT,
            hp=stats.hp,
            moves_left=stats.moves,
            loc=Coord(x=0, y=0),
        )
        state.units[scout.id] = scout
        state.next_unit_id += 1
        state.get_tile(scout.loc).unit_ids.append(scout.id)  # type: ignore[union-attr]

        result = execute_set_automation(
            state,
            "p1",
            SetAutomationAction(unit_id=scout.id, mode=UnitAutomation.AUTO_IMPROVE),
        )
        assert not result.success

    def test_rejects_wrong_owner(self) -> None:
        state = _owned_plains_state()
        worker = _add_worker(state, 0, 0, owner="p1")
        result = execute_set_automation(
            state,
            "p2",
            SetAutomationAction(
                unit_id=worker.id, mode=UnitAutomation.AUTO_IMPROVE
            ),
        )
        assert not result.success

    def test_clear_automation_resets_slot_and_queue(self) -> None:
        state = _owned_plains_state()
        worker = _add_worker(state, 0, 0)
        _set_food_resource(state, 3, 0)
        execute_set_automation(
            state,
            "p1",
            SetAutomationAction(
                unit_id=worker.id, mode=UnitAutomation.AUTO_IMPROVE
            ),
        )
        # Priming the queue with a fake order proves the clear action
        # also drops pending moves (e.g. the head order the automation
        # walked toward).
        resume_automation(state)
        assert worker.orders_queue  # automation queued a move

        result = execute_clear_automation(
            state, "p1", ClearAutomationAction(unit_id=worker.id)
        )
        assert result.success, result.message
        assert worker.automation is None
        assert worker.orders_queue == []


class TestAutoImproveTargeting:
    def test_picks_nearest_food_tile_and_walks_toward_it(self) -> None:
        """Worker at (0,0) with a food tile at (2,0) should queue a move there."""
        state = _owned_plains_state()
        _set_food_resource(state, 2, 0)
        worker = _add_worker(state, 0, 0)
        worker.automation = UnitAutomation.AUTO_IMPROVE

        state.turn = 1
        worker.moves_left = worker.stats.moves
        resume_automation(state)

        # Workers have moves=2 so a distance-2 target is reached in one
        # turn; the automation then builds the FARM and queues a follow-
        # up target (there are none left with FOOD — so we expect the
        # automation to cancel with NO_TARGET after the build).
        improved_tile = state.get_tile(Coord(x=2, y=0))
        assert improved_tile is not None
        assert improved_tile.improvement == ImprovementType.FARM
        assert worker.loc == Coord(x=2, y=0)
        assert worker.automation is None  # NO_TARGET after building
        assert any(
            e.reason == AutomationCancellationReason.NO_TARGET
            for e in state.automation_events
        )

    def test_multi_turn_route_with_queued_order(self) -> None:
        """Distant target requires multiple turns; queue walks forward."""
        state = _owned_plains_state()
        _set_food_resource(state, 5, 0)
        worker = _add_worker(state, 0, 0)
        worker.automation = UnitAutomation.AUTO_IMPROVE

        state.turn = 1
        worker.moves_left = worker.stats.moves
        resume_automation(state)
        # First turn: walk 2 tiles toward (5,0).
        assert worker.loc == Coord(x=2, y=0)
        assert worker.orders_queue  # still marching
        assert worker.automation == UnitAutomation.AUTO_IMPROVE

        state.turn = 2
        worker.moves_left = worker.stats.moves
        # Next turn: queued-order resume advances the worker, then
        # automation short-circuits because the queue still has work.
        resume_queued_orders(state)
        resume_automation(state)
        assert worker.loc == Coord(x=4, y=0)
        assert worker.orders_queue  # still marching
        assert worker.automation == UnitAutomation.AUTO_IMPROVE

        state.turn = 3
        worker.moves_left = worker.stats.moves
        resume_queued_orders(state)
        resume_automation(state)
        # Reached the target and built in this turn's automation pass.
        improved = state.get_tile(Coord(x=5, y=0))
        assert improved is not None
        assert improved.improvement == ImprovementType.FARM

    def test_picks_new_target_after_building(self) -> None:
        """With two food tiles available the worker should chain them."""
        state = _owned_plains_state()
        _set_food_resource(state, 1, 0)
        _set_food_resource(state, 2, 0)
        worker = _add_worker(state, 0, 0)
        worker.automation = UnitAutomation.AUTO_IMPROVE

        state.turn = 1
        worker.moves_left = worker.stats.moves
        resume_automation(state)
        # Worker walks to nearest food tile (1,0), builds FARM, then
        # tries to chain to (2,0) with whatever moves remain. Moves=2,
        # entry=1 for each plains step, farm costs no moves. So after
        # building at (1,0) the worker still has 1 move and queues the
        # next target at (2,0) — stepping there uses the last move.
        first = state.get_tile(Coord(x=1, y=0))
        second = state.get_tile(Coord(x=2, y=0))
        assert first is not None and second is not None
        assert first.improvement == ImprovementType.FARM
        # Worker has moved to or is heading to the second tile.
        assert worker.loc in (Coord(x=1, y=0), Coord(x=2, y=0))


class TestAutomationCancellation:
    def test_enemy_adjacent_cancels(self) -> None:
        """Enemy at Chebyshev distance 1 clears the automation slot."""
        state = _owned_plains_state()
        _set_food_resource(state, 5, 0)
        worker = _add_worker(state, 2, 2)
        worker.automation = UnitAutomation.AUTO_IMPROVE
        _add_enemy(state, 3, 3)  # diagonal, Chebyshev = 1

        state.turn = 1
        worker.moves_left = worker.stats.moves
        resume_automation(state)

        assert worker.automation is None
        assert worker.orders_queue == []
        assert any(
            e.reason == AutomationCancellationReason.ENEMY_ADJACENT
            for e in state.automation_events
        )
        # Distance-2 (Chebyshev) does NOT cancel — sanity check in
        # next test case.

    def test_distant_enemy_does_not_cancel(self) -> None:
        state = _owned_plains_state()
        _set_food_resource(state, 5, 5)
        worker = _add_worker(state, 2, 2)
        worker.automation = UnitAutomation.AUTO_IMPROVE
        _add_enemy(state, 4, 4)  # Chebyshev distance 2

        state.turn = 1
        worker.moves_left = worker.stats.moves
        resume_automation(state)

        assert worker.automation == UnitAutomation.AUTO_IMPROVE

    def test_manual_action_clears_automation(self) -> None:
        """A MoveAction submitted for an automated worker clears the slot."""
        state = _owned_plains_state()
        _set_food_resource(state, 5, 0)
        worker = _add_worker(state, 0, 0)
        worker.automation = UnitAutomation.AUTO_IMPROVE

        actions = {
            "p1": [MoveAction(unit_id=worker.id, to=Coord(x=1, y=0))],
            "p2": [],
        }
        resolve_turn(state, actions)

        assert worker.automation is None
        assert any(
            e.reason == AutomationCancellationReason.MANUAL_OVERRIDE
            for e in state.automation_events
        )

    def test_no_target_available_cancels(self) -> None:
        """Every candidate tile improved → automation clears with NO_TARGET."""
        state = _owned_plains_state()
        worker = _add_worker(state, 0, 0)
        worker.automation = UnitAutomation.AUTO_IMPROVE

        state.turn = 1
        worker.moves_left = worker.stats.moves
        resume_automation(state)

        # No FOOD / ORE / CRYSTAL resource on any tile and no forest
        # tiles — no improvement is legal anywhere.
        assert worker.automation is None
        assert any(
            e.reason == AutomationCancellationReason.NO_TARGET
            for e in state.automation_events
        )


class TestAutomationPersistence:
    def test_legacy_deserialise_defaults_to_none(self) -> None:
        state = _owned_plains_state()
        worker = _add_worker(state, 0, 0)
        dump = state.model_dump(mode="json")
        # Simulate a pre-Phase-6 payload by stripping the new field.
        for unit in dump["units"].values():
            unit.pop("automation", None)
        restored = GameState.model_validate(dump)
        assert restored.units[worker.id].automation is None

    def test_replay_determinism_through_resolve_turn(self) -> None:
        """Same seed + actions → identical automation outcome."""
        state_a = _owned_plains_state()
        _set_food_resource(state_a, 3, 3)
        worker_a = _add_worker(state_a, 0, 0)
        worker_a.automation = UnitAutomation.AUTO_IMPROVE
        state_b = deepcopy(state_a)

        resolve_turn(state_a, {"p1": [], "p2": []})
        resolve_turn(state_b, {"p1": [], "p2": []})

        assert state_a.hash_state() == state_b.hash_state()
