"""
Configuration settings for the 4X game backend.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8010
    secret_key: str = "dev-secret-key"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    max_players_per_game: int = 8
    max_concurrent_games: int = 20
    turn_timeout_seconds: int = 60

    # Shared secret used to verify Auth.js JWTs issued by the Next.js frontend.
    # Must match `AUTH_SECRET` set on the Next.js side. Rotating requires a
    # coordinated redeploy of both services.
    auth_secret: str = "dev-auth-secret-change-me-min-32-bytes-long"
    # Expected `iss` claim on incoming Auth.js JWTs. Auth.js omits `iss` by
    # default; leave empty to skip issuer verification.
    auth_jwt_issuer: str = ""

    # Shared secret used to gate the identity-upsert endpoint the Next.js
    # server route calls on first magic-link verify. Kept distinct from
    # `auth_secret` (which signs user JWTs) so the two rotate independently.
    identity_service_secret: str = "dev-identity-service-secret-change-me"

    # Phase 5 (spectated-agents): auto-archive sweep. Thresholds measured
    # against ``created_at`` (waiting) and ``turn_started_at`` (active).
    # ``archive_sweep_enabled`` gates the in-process background loop only;
    # the ``mise run db-archive-stale`` task ignores the flag and always
    # runs the sweep on demand.
    archive_stale_waiting_days: int = 7
    archive_stale_active_days: int = 14
    archive_sweep_interval_seconds: int = 86400
    archive_sweep_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
