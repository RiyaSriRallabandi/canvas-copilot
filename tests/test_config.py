"""Tests for settings loading."""

from __future__ import annotations

from canvas_copilot.config import Settings


def test_reads_base_url_from_environment(monkeypatch):
    monkeypatch.setenv("CANVAS_BASE_URL", "https://canvas.test/api/v1")
    settings = Settings(_env_file=None)
    assert settings.canvas_base_url == "https://canvas.test/api/v1"


def test_base_url_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("CANVAS_BASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.canvas_base_url == ""
