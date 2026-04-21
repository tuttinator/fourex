"""Phase 5: tech-tree foundation — SCIENCE resource + research loop.

Engine-level invariants:

- ``SCIENCE`` is a first-class resource: ``ResourceBag.science`` exists,
  ``can_afford`` respects it, arithmetic composes correctly.
- Cities produce science per turn from a base rate; Library and Temple
  add on top of the base, and ``collect_resources`` deposits it in the
  player's stockpile.
- Players pick one active tech; the resolver drains stockpile science
  into ``ResearchState.progress`` each turn; completion emits a
  ``ResearchCompletedEvent``, moves the tech to ``completed``, and
  clears ``active`` / ``progress``.
- Starter techs (empty ``requires``) are pre-populated in every
  player's ``completed`` set.
- ``execute_set_active_research`` validates prereqs, rejects
  already-completed techs and unknown ids, and preserves ``progress``
  on mid-research switch (clamped to the new tech's cost).
- ``redact_state`` exposes only the caller's own research state.
- Research advances in sorted ``player_id`` order so replays are
  deterministic.
"""

from backend.src.game.models import (
    CITY_BASE_SCIENCE_PER_TURN,
    LIBRARY_SCIENCE_BONUS,
    STARTER_TECHS,
    TECH_TREE,
    TEMPLE_SCIENCE_BONUS,
    BuildingType,
    City,
    Coord,
    GameState,
    ResearchState,
    ResourceBag,
    SetActiveResearchAction,
    Terrain,
    Tile,
)
from backend.src.game.rules import (
    _ensure_research_state,
    advance_research,
    collect_resources,
    execute_set_active_research,
    redact_state,
    resolve_turn,
    seed_research,
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


def _seed_city(
    state: GameState, owner: str, loc: tuple[int, int], city_id: int = 1
) -> City:
    city = City(id=city_id, owner=owner, loc=Coord(x=loc[0], y=loc[1]))
    state.cities[city_id] = city
    tile = state.get_tile(city.loc)
    assert tile is not None
    tile.city_id = city_id
    tile.owner = owner
    return city


class TestScienceResource:
    def test_resourcebag_carries_science(self):
        bag = ResourceBag(science=5)
        assert bag.science == 5
        assert (bag + ResourceBag(science=3)).science == 8
        assert (bag - ResourceBag(science=2)).science == 3

    def test_can_afford_respects_science(self):
        bag = ResourceBag(food=100, science=2)
        assert bag.can_afford(ResourceBag(science=2)) is True
        assert bag.can_afford(ResourceBag(science=3)) is False


class TestCityScienceProduction:
    def test_base_science_per_turn(self):
        state = _plains_grid()
        city = _seed_city(state, "p1", (5, 5))
        assert city.science_per_turn() == CITY_BASE_SCIENCE_PER_TURN

    def test_library_boosts_science(self):
        state = _plains_grid()
        city = _seed_city(state, "p1", (5, 5))
        city.buildings.add(BuildingType.LIBRARY)
        assert (
            city.science_per_turn()
            == CITY_BASE_SCIENCE_PER_TURN + LIBRARY_SCIENCE_BONUS
        )

    def test_temple_boosts_science(self):
        state = _plains_grid()
        city = _seed_city(state, "p1", (5, 5))
        city.buildings.add(BuildingType.TEMPLE)
        assert (
            city.science_per_turn()
            == CITY_BASE_SCIENCE_PER_TURN + TEMPLE_SCIENCE_BONUS
        )

    def test_library_and_temple_stack(self):
        state = _plains_grid()
        city = _seed_city(state, "p1", (5, 5))
        city.buildings.add(BuildingType.LIBRARY)
        city.buildings.add(BuildingType.TEMPLE)
        assert (
            city.science_per_turn()
            == CITY_BASE_SCIENCE_PER_TURN
            + LIBRARY_SCIENCE_BONUS
            + TEMPLE_SCIENCE_BONUS
        )

    def test_collect_resources_deposits_science(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag()
        city = _seed_city(state, "p1", (5, 5))
        city.buildings.add(BuildingType.LIBRARY)

        collect_resources(state)

        expected = CITY_BASE_SCIENCE_PER_TURN + LIBRARY_SCIENCE_BONUS
        assert state.stockpiles["p1"].science == expected


class TestSeedResearch:
    def test_starter_techs_pre_completed(self):
        state = _plains_grid()
        seed_research(state, ["p1", "p2"])
        for player in ("p1", "p2"):
            rs = state.research[player]
            assert set(rs.completed) == set(STARTER_TECHS)
            assert rs.active is None
            assert rs.progress == 0

    def test_seed_is_idempotent(self):
        state = _plains_grid()
        seed_research(state, ["p1"])
        state.research["p1"].progress = 42
        seed_research(state, ["p1"])
        # Existing entry untouched.
        assert state.research["p1"].progress == 42

    def test_ensure_research_state_autoseeds(self):
        state = _plains_grid()
        research = _ensure_research_state(state, "p1")
        assert set(research.completed) == set(STARTER_TECHS)


class TestSetActiveResearch:
    def _state_with_player(self) -> GameState:
        state = _plains_grid()
        state.players = ["p1"]
        seed_research(state, ["p1"])
        return state

    def test_set_valid_tech(self):
        state = self._state_with_player()
        # Pick a non-starter tech whose prereqs are the starter set.
        # ``masonry`` requires ``bronze_working`` which is a starter.
        tech_id = "masonry"
        assert TECH_TREE[tech_id].requires == ["bronze_working"]
        assert "bronze_working" in state.research["p1"].completed

        result = execute_set_active_research(
            state, "p1", SetActiveResearchAction(tech_id=tech_id)
        )
        assert result.success is True
        assert state.research["p1"].active == tech_id

    def test_reject_unknown_tech(self):
        state = self._state_with_player()
        result = execute_set_active_research(
            state, "p1", SetActiveResearchAction(tech_id="unobtainium")
        )
        assert result.success is False
        assert "Unknown tech" in result.message

    def test_reject_already_completed(self):
        state = self._state_with_player()
        # Every starter tech is already in completed.
        starter = STARTER_TECHS[0]
        result = execute_set_active_research(
            state, "p1", SetActiveResearchAction(tech_id=starter)
        )
        assert result.success is False
        assert "already researched" in result.message

    def test_reject_missing_prereq(self):
        state = self._state_with_player()
        # mysticism requires writing, which requires pottery (starter).
        # Remove pottery and writing to guarantee a missing prereq.
        state.research["p1"].completed = [
            t for t in state.research["p1"].completed if t != "pottery"
        ]
        # writing is not in completed either.
        result = execute_set_active_research(
            state, "p1", SetActiveResearchAction(tech_id="mysticism")
        )
        assert result.success is False
        assert "requires" in result.message

    def test_clear_active_preserves_progress(self):
        state = self._state_with_player()
        state.research["p1"].active = "masonry"
        state.research["p1"].progress = 7

        result = execute_set_active_research(
            state, "p1", SetActiveResearchAction(tech_id=None)
        )
        assert result.success is True
        assert state.research["p1"].active is None
        # Progress survives the clear — the invested science is not lost.
        assert state.research["p1"].progress == 7

    def test_switch_clamps_progress_to_new_cost(self):
        state = self._state_with_player()
        state.research["p1"].active = "writing"  # cost 15
        state.research["p1"].progress = 15

        # Switching to masonry (cost 10) clamps progress to 10.
        result = execute_set_active_research(
            state, "p1", SetActiveResearchAction(tech_id="masonry")
        )
        assert result.success is True
        assert state.research["p1"].active == "masonry"
        assert state.research["p1"].progress == TECH_TREE["masonry"].cost_science


class TestAdvanceResearch:
    def test_drains_stockpile_into_progress(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(science=5)
        seed_research(state, ["p1"])
        state.research["p1"].active = "masonry"  # cost 10

        events = advance_research(state)

        assert events == []
        assert state.stockpiles["p1"].science == 0
        assert state.research["p1"].progress == 5
        assert state.research["p1"].active == "masonry"

    def test_completion_emits_event_and_clears_active(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(science=10)
        seed_research(state, ["p1"])
        state.research["p1"].active = "masonry"

        events = advance_research(state)

        assert len(events) == 1
        event = events[0]
        assert event.player_id == "p1"
        assert event.tech_id == "masonry"
        assert BuildingType.WALLS in event.unlocks_buildings
        assert state.research["p1"].active is None
        assert state.research["p1"].progress == 0
        assert "masonry" in state.research["p1"].completed

    def test_overshoot_bounded_by_remaining_cost(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(science=100)
        seed_research(state, ["p1"])
        state.research["p1"].active = "masonry"  # cost 10

        advance_research(state)

        # Only 10 drained — the rest stays in the stockpile.
        assert state.stockpiles["p1"].science == 90

    def test_no_active_no_progress(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag(science=50)
        seed_research(state, ["p1"])

        events = advance_research(state)

        assert events == []
        # Science just sits in the stockpile until an active tech is set.
        assert state.stockpiles["p1"].science == 50

    def test_zero_cost_tech_completes_on_first_tick(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag()
        seed_research(state, ["p1"])
        # Force a zero-cost tech by taking pottery out of the starter
        # set. (In the real game pottery is a starter — this only tests
        # the boundary.)
        state.research["p1"].completed = [
            t for t in state.research["p1"].completed if t != "pottery"
        ]
        state.research["p1"].active = "pottery"

        events = advance_research(state)

        assert len(events) == 1
        assert events[0].tech_id == "pottery"

    def test_sorted_player_iteration_is_deterministic(self):
        state = _plains_grid()
        state.players = ["zed", "alice"]
        # Both stockpiles fully fund masonry (cost 10) so each emits.
        state.stockpiles["alice"] = ResourceBag(science=10)
        state.stockpiles["zed"] = ResourceBag(science=10)
        seed_research(state, ["zed", "alice"])
        state.research["alice"].active = "masonry"
        state.research["zed"].active = "masonry"

        events = advance_research(state)

        # Emission order reflects sorted player id iteration.
        assert [e.player_id for e in events] == ["alice", "zed"]


class TestResolveTurnIntegration:
    def test_science_income_funds_active_tech_same_turn(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag()
        seed_research(state, ["p1"])
        city = _seed_city(state, "p1", (5, 5))
        city.buildings.add(BuildingType.LIBRARY)
        state.research["p1"].active = "masonry"

        # Turn 1: base 1 + library 2 = 3 science → progress 3, active still set.
        result = resolve_turn(state, {"p1": []})
        assert result.research_completed == []
        assert state.research["p1"].progress == 3

    def test_research_completion_event_surfaces_on_turn_result(self):
        state = _plains_grid()
        state.players = ["p1"]
        # Over-fund the tech so it completes in one turn.
        state.stockpiles["p1"] = ResourceBag(science=20)
        seed_research(state, ["p1"])
        _seed_city(state, "p1", (5, 5))
        state.research["p1"].active = "masonry"

        result = resolve_turn(state, {"p1": []})

        assert len(result.research_completed) == 1
        assert result.research_completed[0].tech_id == "masonry"
        assert state.research["p1"].active is None
        assert "masonry" in state.research["p1"].completed

    def test_submit_set_active_research_action_via_resolver(self):
        state = _plains_grid()
        state.players = ["p1"]
        state.stockpiles["p1"] = ResourceBag()
        seed_research(state, ["p1"])
        _seed_city(state, "p1", (5, 5))

        result = resolve_turn(
            state,
            {"p1": [SetActiveResearchAction(tech_id="masonry")]},
        )

        # The action succeeded.
        assert result.player_actions["p1"][0].success is True
        assert state.research["p1"].active == "masonry"
        # And the city's science income has started accruing into progress.
        assert state.research["p1"].progress == CITY_BASE_SCIENCE_PER_TURN


class TestRedaction:
    def test_player_sees_only_own_research(self):
        state = _plains_grid()
        state.players = ["p1", "p2"]
        seed_research(state, ["p1", "p2"])
        state.research["p1"].active = "masonry"
        state.research["p1"].progress = 4
        state.research["p2"].active = "writing"
        state.research["p2"].progress = 9

        redacted = redact_state(state, "p1")

        assert "p1" in redacted.research
        assert "p2" not in redacted.research
        assert redacted.research["p1"].active == "masonry"
        assert redacted.research["p1"].progress == 4

    def test_player_with_no_research_gets_empty_dict(self):
        state = _plains_grid()
        state.players = ["p1"]
        # Deliberately skip seeding.
        redacted = redact_state(state, "p1")
        assert redacted.research == {}


class TestDeterminism:
    def test_replay_produces_identical_research_state(self):
        def run() -> GameState:
            state = _plains_grid()
            state.players = ["alice", "bob"]
            state.stockpiles["alice"] = ResourceBag(science=6)
            state.stockpiles["bob"] = ResourceBag(science=6)
            seed_research(state, ["alice", "bob"])
            _seed_city(state, "alice", (3, 3), city_id=1)
            _seed_city(state, "bob", (7, 7), city_id=2)
            state.research["alice"].active = "masonry"
            state.research["bob"].active = "writing"

            for _ in range(3):
                resolve_turn(state, {"alice": [], "bob": []})
            return state

        a = run()
        b = run()
        assert a.hash_state() == b.hash_state()


class TestResearchStateShape:
    def test_research_state_round_trips_through_json(self):
        original = ResearchState(
            completed=["pottery", "bronze_working"],
            active="masonry",
            progress=3,
        )
        dumped = original.model_dump(mode="json")
        restored = ResearchState.model_validate(dumped)
        assert restored == original
