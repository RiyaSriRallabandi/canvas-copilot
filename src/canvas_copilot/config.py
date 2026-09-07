"""Application configuration.

Only non-secret settings live here. The Canvas access token is deliberately
NOT a setting — it is stored in the OS keychain (see ``canvas_copilot.auth``)
so it never sits in a file or environment variable.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from the environment or a local ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # e.g. https://canvas.cmu.edu/api/v1
    canvas_base_url: str = ""

    # Local Ollama models + host.
    model: str = "qwen2.5:3b"
    embed_model: str = "nomic-embed-text"
    ollama_host: str = "http://localhost:11434"


@lru_cache
def get_settings() -> Settings:
    return Settings()
