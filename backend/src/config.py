"""
Configuration settings for the 4X game backend.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "dev-secret-key"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    max_players_per_game: int = 8
    max_concurrent_games: int = 20
    turn_timeout_seconds: int = 60

    class Config:
        env_file = ".env"


settings = Settings()