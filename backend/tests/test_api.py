"""
Tests for FastAPI endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from backend.src.main import app
from backend.src.api.game_controller import GameController


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Authentication headers for testing."""
    return {"Authorization": "Bearer player_test_player_1"}


class TestHealthEndpoints:
    """Test health check endpoints."""
    
    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
    
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestGameEndpoints:
    """Test game-related API endpoints."""
    
    def test_start_game(self, client, auth_headers):
        """Test creating a new game."""
        response = client.post(
            "/api/v1/games/test_game/start",
            json={"players": ["player_1", "player_2"], "seed": 42},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "game_created"
        assert data["game_id"] == "test_game"
    
    def test_list_games(self, client, auth_headers):
        """Test listing games."""
        # First create a game
        client.post(
            "/api/v1/games/test_game_2/start",
            json={"players": ["player_1", "player_2"], "seed": 42},
            headers=auth_headers,
        )
        
        # Then list games
        response = client.get("/api/v1/games", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "games" in data
        assert "test_game_2" in data["games"]
    
    def test_get_game_state(self, client, auth_headers):
        """Test getting game state."""
        # Create game first
        client.post(
            "/api/v1/games/test_game_3/start",
            json={"players": ["test_player_1", "test_player_2"], "seed": 42},
            headers=auth_headers,
        )
        
        # Get state
        response = client.get(
            "/api/v1/state?game_id=test_game_3",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "turn" in data
        assert "players" in data
        assert "tiles" in data
    
    def test_submit_actions(self, client, auth_headers):
        """Test submitting player actions."""
        # Create game first
        client.post(
            "/api/v1/games/test_game_4/start",
            json={"players": ["test_player_1", "test_player_2"], "seed": 42},
            headers=auth_headers,
        )
        
        # Submit empty actions
        response = client.post(
            "/api/v1/actions?game_id=test_game_4",
            json=[],
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "actions_submitted"
        assert data["count"] == 0
    
    def test_submit_prompt_log(self, client, auth_headers):
        """Test submitting prompt logs."""
        # Create game first
        client.post(
            "/api/v1/games/test_game_5/start",
            json={"players": ["test_player_1", "test_player_2"], "seed": 42},
            headers=auth_headers,
        )
        
        # Submit prompt log
        prompt_data = {
            "player": "test_player_1",
            "prompt": "What should I do?",
            "response": "Move scout north",
            "tokens_in": 10,
            "tokens_out": 5,
            "latency_ms": 150,
        }
        
        response = client.post(
            "/api/v1/prompts?game_id=test_game_5",
            json=prompt_data,
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "prompt_logged"


class TestAuthentication:
    """Test authentication and authorization."""
    
    def test_missing_auth_header(self, client):
        """Test that endpoints require authentication."""
        response = client.get("/api/v1/state")
        assert response.status_code == 403  # Forbidden due to missing auth
    
    def test_invalid_token_format(self, client):
        """Test invalid token format."""
        headers = {"Authorization": "Bearer invalid_format"}
        response = client.get("/api/v1/state", headers=headers)
        assert response.status_code == 401
        data = response.json()
        assert "Invalid token format" in data["detail"]
    
    def test_valid_token_format(self, client):
        """Test valid token format (even if game doesn't exist)."""
        headers = {"Authorization": "Bearer player_test_player"}
        response = client.get("/api/v1/state", headers=headers)
        # Should return 404 for missing game, not 401 for invalid auth
        assert response.status_code == 404


class TestErrorHandling:
    """Test error handling in API endpoints."""
    
    def test_game_not_found(self, client, auth_headers):
        """Test getting state for non-existent game."""
        response = client.get(
            "/api/v1/state?game_id=nonexistent",
            headers=auth_headers,
        )
        assert response.status_code == 404
        data = response.json()
        assert "Game not found" in data["detail"]
    
    def test_duplicate_game_creation(self, client, auth_headers):
        """Test creating game with duplicate ID."""
        game_data = {"players": ["player_1", "player_2"], "seed": 42}
        
        # Create first game
        response1 = client.post(
            "/api/v1/games/duplicate_test/start",
            json=game_data,
            headers=auth_headers,
        )
        assert response1.status_code == 200
        
        # Try to create duplicate
        response2 = client.post(
            "/api/v1/games/duplicate_test/start",
            json=game_data,
            headers=auth_headers,
        )
        assert response2.status_code == 400
        data = response2.json()
        assert "already exists" in data["detail"]
    
    def test_invalid_player_count(self, client, auth_headers):
        """Test creating game with invalid player count."""
        # Too few players
        response = client.post(
            "/api/v1/games/invalid_count/start",
            json={"players": ["player_1"], "seed": 42},
            headers=auth_headers,
        )
        assert response.status_code == 400
        data = response.json()
        assert "2-8 players" in data["detail"]
        
        # Too many players
        response = client.post(
            "/api/v1/games/invalid_count_2/start",
            json={"players": [f"player_{i}" for i in range(10)], "seed": 42},
            headers=auth_headers,
        )
        assert response.status_code == 400
        data = response.json()
        assert "2-8 players" in data["detail"]