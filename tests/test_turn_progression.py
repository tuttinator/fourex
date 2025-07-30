"""
End-to-end tests for turn progression and game mechanics.
"""

import asyncio
import time
from typing import Any

import pytest
import requests

from agents.src.agent import FourXAgent


class TestTurnProgression:
    """Test turn progression and game state management."""

    @pytest.fixture
    def base_url(self):
        return "http://localhost:8000/api/v1"

    @pytest.fixture
    def game_id(self):
        return f"test_game_{int(time.time())}"

    @pytest.fixture
    def players(self):
        return ["TestAlice", "TestBob"]

    def setup_game(self, base_url: str, game_id: str, players: list[str]) -> bool:
        """Set up a test game."""
        try:
            # Create game
            response = requests.post(
                f"{base_url}/games/{game_id}/start",
                json={"players": players, "seed": 42},
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to setup game: {e}")
            return False

    def get_game_state(self, base_url: str, game_id: str) -> dict[str, Any]:
        """Get current game state."""
        try:
            response = requests.get(f"{base_url}/state?game_id={game_id}")
            if response.status_code == 200:
                return response.json()
            return {}
        except Exception:
            return {}

    def submit_simple_action(self, base_url: str, game_id: str, player_id: str) -> bool:
        """Submit a simple pass action for a player."""
        try:
            # Get game state to find units
            state = self.get_game_state(base_url, game_id)
            if not state:
                return False

            # Find player's units
            my_units = [u for u in state["units"].values() if u["owner"] == player_id]
            if not my_units:
                return False

            # Create a simple move action
            unit = my_units[0]
            current_x, current_y = unit["loc"]["x"], unit["loc"]["y"]

            # Move one tile (simple movement)
            actions = [
                {
                    "type": "MOVE",
                    "unit_id": unit["id"],
                    "to": {"x": current_x + 1, "y": current_y},
                }
            ]

            # Submit actions
            response = requests.post(
                f"{base_url}/actions?game_id={game_id}",
                json=actions,
                headers={"Authorization": f"Bearer player_{player_id}"},
            )

            return response.status_code == 200

        except Exception as e:
            print(f"Failed to submit action for {player_id}: {e}")
            return False

    def test_basic_turn_progression(self, base_url, game_id, players):
        """Test that turns progress when all players submit actions."""
        # Setup game
        assert self.setup_game(base_url, game_id, players), "Failed to setup game"

        # Wait for game initialization
        time.sleep(1)

        # Get initial state
        initial_state = self.get_game_state(base_url, game_id)
        assert initial_state, "Failed to get initial game state"
        assert (
            initial_state["turn"] == 0
        ), f"Expected turn 0, got {initial_state['turn']}"

        # Both players submit actions
        for player in players:
            success = self.submit_simple_action(base_url, game_id, player)
            assert success, f"Failed to submit action for {player}"

        # Wait for turn processing
        time.sleep(2)

        # Check that turn advanced
        final_state = self.get_game_state(base_url, game_id)
        assert final_state, "Failed to get final game state"
        assert final_state["turn"] == 1, f"Expected turn 1, got {final_state['turn']}"

        print(
            f"✅ Turn progressed from {initial_state['turn']} to {final_state['turn']}"
        )

    def test_partial_submissions_dont_advance_turn(self, base_url, game_id, players):
        """Test that turns don't advance when only some players submit actions."""
        # Setup game
        assert self.setup_game(base_url, game_id, players), "Failed to setup game"
        time.sleep(1)

        # Get initial state
        initial_state = self.get_game_state(base_url, game_id)
        assert initial_state["turn"] == 0

        # Only first player submits actions
        success = self.submit_simple_action(base_url, game_id, players[0])
        assert success, f"Failed to submit action for {players[0]}"

        # Wait briefly
        time.sleep(1)

        # Check that turn hasn't advanced
        intermediate_state = self.get_game_state(base_url, game_id)
        assert intermediate_state["turn"] == 0, "Turn advanced with partial submissions"

        print("✅ Turn correctly stayed at 0 with partial submissions")

    @pytest.mark.asyncio
    async def test_agent_integration(self, base_url, game_id, players):
        """Test full agent integration with turn progression."""
        # Setup game
        assert self.setup_game(base_url, game_id, players), "Failed to setup game"
        time.sleep(1)

        # Create agents
        agents = []
        for player in players:
            agent = FourXAgent(
                player_id=player,
                personality="balanced",
                game_backend_url=base_url,
                use_persistent_client=True,
            )
            agents.append(agent)

        # Get initial state
        initial_state = self.get_game_state(base_url, game_id)
        assert initial_state["turn"] == 0

        # Have both agents play one turn
        tasks = []
        for agent in agents:
            task = asyncio.create_task(agent.play_turn(game_id))
            tasks.append(task)

        # Wait for both agents to complete their turns
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check that both agents succeeded
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                pytest.fail(f"Agent {players[i]} failed: {result}")
            assert result, f"Agent {players[i]} returned False"

        # Wait for turn processing
        time.sleep(2)

        # Check final state
        final_state = self.get_game_state(base_url, game_id)
        assert final_state["turn"] == 1, f"Expected turn 1, got {final_state['turn']}"

        print("✅ Full agent integration test passed")

    def test_database_persistence(self, base_url, game_id, players):
        """Test that game state persists in database."""
        # Setup game
        assert self.setup_game(base_url, game_id, players), "Failed to setup game"
        time.sleep(1)

        # Submit actions to advance turn
        for player in players:
            success = self.submit_simple_action(base_url, game_id, player)
            assert success, f"Failed to submit action for {player}"

        time.sleep(2)

        # Get game info from database
        try:
            response = requests.get(f"{base_url}/games/{game_id}/info")
            assert response.status_code == 200, "Failed to get game info"

            game_info = response.json()
            assert (
                game_info["turn"] >= 1
            ), f"Database shows turn {game_info['turn']}, expected >= 1"
            assert game_info["players"] == players, "Players mismatch in database"

            print(f"✅ Database correctly shows turn {game_info['turn']}")

        except Exception as e:
            pytest.fail(f"Database persistence test failed: {e}")


if __name__ == "__main__":
    # Run basic tests manually
    import sys

    test = TestTurnProgression()
    base_url = "http://localhost:8000/api/v1"
    game_id = f"manual_test_{int(time.time())}"
    players = ["ManualAlice", "ManualBob"]

    print("🧪 Running manual turn progression tests...")

    try:
        # Test 1: Basic turn progression
        print("\n1. Testing basic turn progression...")
        test.test_basic_turn_progression(base_url, game_id + "_1", players)

        # Test 2: Partial submissions
        print("\n2. Testing partial submissions...")
        test.test_partial_submissions_dont_advance_turn(
            base_url, game_id + "_2", players
        )

        # Test 3: Database persistence
        print("\n3. Testing database persistence...")
        test.test_database_persistence(base_url, game_id + "_3", players)

        print("\n✅ All tests passed!")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
