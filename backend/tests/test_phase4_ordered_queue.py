"""Phase 4: ordered production queue — append / cancel / reorder.

Phase 4 makes ``City.build_queue`` an ordered ``list[BuildJob]``. Three
new actions drive it: ``SET_CITY_PRODUCTION`` appends, ``CANCEL_CITY_
PRODUCTION`` removes by index (index 0 forfeits progress, higher indices
refund resources), ``REORDER_CITY_QUEUE`` permutes. The Phase 3 wrapper
actions (``TrainUnitAction`` / ``BuildBuildingAction``) keep working and
simply append — verified in the legacy Phase 3 tests.

These tests hit each acceptance criterion from
``plans/sprites-production-tech.md`` at the engine level.
"""

from backend.src.game.models import (
    UNIT_PRODUCTION_COST,
    BuildingType,
    CancelCityProductionAction,
    City,
    Coord,
    GameState,
    ReorderCityQueueAction,
    ResourceBag,
    SetCityProductionAction,
    Terrain,
    Tile,
    TrainUnitAction,
    UnitType,
)
from backend.src.game.rules import (
    advance_production,
    execute_cancel_city_production,
    execute_reorder_city_queue,
    execute_set_city_production,
    execute_train_unit,
    redact_state,
    resolve_turn,
)


def _plains_grid(width: int = 10, height: int = 10) -> GameState:
    state = GameState(map_width=width, map_height=height)
    tile_id = 0
    for y in range(height):
        for x in range(width):
            state.tiles.append(
                Tile(id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.PLAINS)
            )
            tile_id += 1
    return state


def _seed_city(state: GameState, player: str, x: int, y: int, city_id: int = 1) -> City:
    city = City(id=city_id, owner=player, loc=Coord(x=x, y=y))
    state.cities[city_id] = city
    tile = state.get_tile(Coord(x=x, y=y))
    assert tile is not None
    tile.city_id = city_id
    tile.owner = player
    return city


class TestSetCityProduction:
    def test_appends_unit_to_empty_queue(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_set_city_production(
            state,
            "p1",
            SetCityProductionAction(city_id=city.id, unit_type=UnitType.SCOUT),
        )

        assert result.success is True
        assert len(city.build_queue) == 1
        assert city.build_queue[0].type == "unit"
        assert city.build_queue[0].target == UnitType.SCOUT.value

    def test_appends_behind_existing_jobs(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, ore=100)
        city = _seed_city(state, "p1", 5, 5)

        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        execute_set_city_production(
            state,
            "p1",
            SetCityProductionAction(city_id=city.id, unit_type=UnitType.SOLDIER),
        )

        assert [j.target for j in city.build_queue] == [
            UnitType.SCOUT.value,
            UnitType.SOLDIER.value,
        ]

    def test_appends_building(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(wood=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_set_city_production(
            state,
            "p1",
            SetCityProductionAction(
                city_id=city.id, building_type=BuildingType.GRANARY
            ),
        )
        assert result.success is True
        assert city.build_queue[0].type == "building"
        assert city.build_queue[0].target == BuildingType.GRANARY.value

    def test_rejects_non_owner(self):
        state = _plains_grid()
        state.players = ["p1", "p2"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        state.stockpiles["p2"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_set_city_production(
            state,
            "p2",
            SetCityProductionAction(city_id=city.id, unit_type=UnitType.SCOUT),
        )
        assert result.success is False
        assert city.build_queue == []

    def test_rejects_both_types_set(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, wood=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_set_city_production(
            state,
            "p1",
            SetCityProductionAction(
                city_id=city.id,
                unit_type=UnitType.SCOUT,
                building_type=BuildingType.GRANARY,
            ),
        )
        assert result.success is False

    def test_rejects_neither_type_set(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        result = execute_set_city_production(
            state, "p1", SetCityProductionAction(city_id=city.id)
        )
        assert result.success is False


class TestCancelCityProduction:
    def test_cancel_active_forfeits_progress_no_refund(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        # Soldier costs food=10 at queue time (scout cost).
        food_after_queue = state.stockpiles["p1"].food
        # Advance a turn so there's progress to forfeit.
        advance_production(state)
        assert city.build_queue[0].progress == 2

        result = execute_cancel_city_production(
            state, "p1", CancelCityProductionAction(city_id=city.id, queue_index=0)
        )
        assert result.success is True
        assert city.build_queue == []
        # No refund: food stays at "post-queue" level.
        assert state.stockpiles["p1"].food == food_after_queue

    def test_cancel_waiting_refunds_resources(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, ore=100)
        city = _seed_city(state, "p1", 5, 5)

        # Two jobs queued. Cancel the waiting one (index 1).
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SOLDIER)
        )
        # Scout: -10 food. Soldier: -15 food, -5 ore.
        assert state.stockpiles["p1"].food == 100 - 10 - 15
        assert state.stockpiles["p1"].ore == 100 - 5

        result = execute_cancel_city_production(
            state, "p1", CancelCityProductionAction(city_id=city.id, queue_index=1)
        )
        assert result.success is True
        # Scout remains queued, soldier resources refunded.
        assert [j.target for j in city.build_queue] == [UnitType.SCOUT.value]
        assert state.stockpiles["p1"].food == 100 - 10  # scout cost only
        assert state.stockpiles["p1"].ore == 100  # fully refunded

    def test_cancel_out_of_range_rejected(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )

        result = execute_cancel_city_production(
            state, "p1", CancelCityProductionAction(city_id=city.id, queue_index=5)
        )
        assert result.success is False
        assert len(city.build_queue) == 1

    def test_cancel_non_owner_rejected(self):
        state = _plains_grid()
        state.players = ["p1", "p2"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        state.stockpiles["p2"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )

        result = execute_cancel_city_production(
            state, "p2", CancelCityProductionAction(city_id=city.id, queue_index=0)
        )
        assert result.success is False
        assert len(city.build_queue) == 1


class TestReorderCityQueue:
    def test_reorder_permutes_queue(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, ore=100, wood=100)
        city = _seed_city(state, "p1", 5, 5)

        # Build a 3-item queue.
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SOLDIER)
        )
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.ARCHER)
        )
        # Give the scout some progress so we can prove progress carries.
        advance_production(state)
        assert city.build_queue[0].progress == 2

        # Reverse the queue. Scout moves from index 0 to 2; its progress
        # travels with it.
        result = execute_reorder_city_queue(
            state,
            "p1",
            ReorderCityQueueAction(city_id=city.id, new_order=[2, 1, 0]),
        )
        assert result.success is True
        targets = [j.target for j in city.build_queue]
        assert targets == [
            UnitType.ARCHER.value,
            UnitType.SOLDIER.value,
            UnitType.SCOUT.value,
        ]
        # Scout's progress is preserved at index 2.
        assert city.build_queue[2].progress == 2

    def test_reorder_rejects_non_permutation(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.WORKER)
        )

        # Wrong length.
        r1 = execute_reorder_city_queue(
            state, "p1", ReorderCityQueueAction(city_id=city.id, new_order=[0])
        )
        assert r1.success is False

        # Duplicates.
        r2 = execute_reorder_city_queue(
            state, "p1", ReorderCityQueueAction(city_id=city.id, new_order=[0, 0])
        )
        assert r2.success is False

        # Out-of-range index.
        r3 = execute_reorder_city_queue(
            state, "p1", ReorderCityQueueAction(city_id=city.id, new_order=[0, 5])
        )
        assert r3.success is False

        # Queue still intact.
        assert [j.target for j in city.build_queue] == [
            UnitType.SCOUT.value,
            UnitType.WORKER.value,
        ]

    def test_reorder_rejects_non_owner(self):
        state = _plains_grid()
        state.players = ["p1", "p2"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.WORKER)
        )

        result = execute_reorder_city_queue(
            state,
            "p2",
            ReorderCityQueueAction(city_id=city.id, new_order=[1, 0]),
        )
        assert result.success is False


class TestAutoAdvanceToNextJob:
    def test_next_job_becomes_active_after_completion(self):
        """When the head job completes, the next queued job becomes
        active on the following turn. Acceptance criterion:
        'no explicit player action required to advance'."""
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        # Two scouts queued. Scout cost=5, rate=2 → 3 turns each.
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )

        # Turns 1-3 drive the first scout to completion.
        for turn in range(3):
            advance_production(state)

        # After the third advance, the first scout has materialised and
        # the second scout is now at head. It has NOT advanced this turn
        # — the "one job per turn" invariant.
        assert len(state.units) == 1
        assert len(city.build_queue) == 1
        assert city.build_queue[0].progress == 0

        # Next turn the new head advances normally.
        advance_production(state)
        assert city.build_queue[0].progress == 2


class TestRedactFullQueue:
    def test_redact_elides_all_queue_entries_for_non_owner(self):
        state = _plains_grid()
        state.players = ["p1", "p2"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        state.stockpiles["p2"] = ResourceBag(food=100, ore=100)
        city_p2 = _seed_city(state, "p2", 5, 5)

        # Give p1 line of sight via a scout adjacent to p2's city.
        from backend.src.game.models import Unit

        state.units[100] = Unit(
            id=100,
            owner="p1",
            type=UnitType.SCOUT,
            hp=2,
            moves_left=3,
            loc=Coord(x=4, y=5),
        )
        state.next_unit_id = 101

        # Queue three jobs on p2's city.
        execute_train_unit(
            state, TrainUnitAction(city_id=city_p2.id, unit_type=UnitType.SCOUT)
        )
        execute_train_unit(
            state, TrainUnitAction(city_id=city_p2.id, unit_type=UnitType.SOLDIER)
        )
        execute_train_unit(
            state, TrainUnitAction(city_id=city_p2.id, unit_type=UnitType.WORKER)
        )
        assert len(city_p2.build_queue) == 3

        redacted = redact_state(state, "p1")
        # p1 can see the city (via scout adjacency) but not any queue entries.
        assert city_p2.id in redacted.cities
        assert redacted.cities[city_p2.id].build_queue == []

        # Owner still sees the full queue.
        redacted_owner = redact_state(state, "p2")
        assert len(redacted_owner.cities[city_p2.id].build_queue) == 3


class TestReplayDeterminismUnderPhase4:
    def test_replay_with_reorder(self):
        """Same seed + same reorder action ⇒ identical hash. Guards the
        engine's deterministic-replay invariant through the new
        queue-manipulation code path."""
        state_a = _plains_grid()
        state_a.players = ["p1"]
        state_a.stockpiles["p1"] = ResourceBag(food=100, ore=100, wood=100)
        _seed_city(state_a, "p1", 5, 5)

        state_b = _plains_grid()
        state_b.players = ["p1"]
        state_b.stockpiles["p1"] = ResourceBag(food=100, ore=100, wood=100)
        _seed_city(state_b, "p1", 5, 5)

        actions_sequence: list[dict] = [
            {
                "p1": [
                    TrainUnitAction(city_id=1, unit_type=UnitType.SCOUT),
                    TrainUnitAction(city_id=1, unit_type=UnitType.SOLDIER),
                ]
            },
            {"p1": [ReorderCityQueueAction(city_id=1, new_order=[1, 0])]},
            {"p1": []},
        ]
        hashes_a = []
        hashes_b = []
        for actions in actions_sequence:
            resolve_turn(state_a, actions)
            resolve_turn(state_b, actions)
            hashes_a.append(state_a.hash_state())
            hashes_b.append(state_b.hash_state())
        assert hashes_a == hashes_b


class TestLegacyWrappersStillAppend:
    """The Phase 3 wrapper actions continue to work in Phase 4 — they
    just append to the queue instead of rejecting when busy."""

    def test_two_train_unit_actions_both_queue(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100, ore=100)
        city = _seed_city(state, "p1", 5, 5)

        r1 = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SCOUT)
        )
        r2 = execute_train_unit(
            state, TrainUnitAction(city_id=city.id, unit_type=UnitType.SOLDIER)
        )
        assert r1.success is True and r2.success is True
        assert len(city.build_queue) == 2


class TestAcceptanceCostShape:
    def test_total_cost_matches_static_table(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(food=100)
        city = _seed_city(state, "p1", 5, 5)

        execute_set_city_production(
            state,
            "p1",
            SetCityProductionAction(city_id=city.id, unit_type=UnitType.SCOUT),
        )
        assert city.build_queue[0].total_cost == UNIT_PRODUCTION_COST[UnitType.SCOUT]
