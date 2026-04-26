"""Tests for the env-driven Settings parser."""

import pytest

from backend.src.config import Settings


def test_cors_origins_default() -> None:
    settings = Settings()
    assert "http://localhost:3000" in settings.cors_origins


def test_cors_origins_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS", '["https://parley.quest","https://www.parley.quest"]'
    )
    settings = Settings()
    assert settings.cors_origins == [
        "https://parley.quest",
        "https://www.parley.quest",
    ]


def test_cors_origins_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS", "https://parley.quest, https://www.parley.quest"
    )
    settings = Settings()
    assert settings.cors_origins == [
        "https://parley.quest",
        "https://www.parley.quest",
    ]


def test_cors_origins_single_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://parley.quest")
    settings = Settings()
    assert settings.cors_origins == ["https://parley.quest"]
