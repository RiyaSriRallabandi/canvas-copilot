"""Versioned prompt files, loaded as text so changes show up in git diffs."""

from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8").strip()


def system_prompt() -> str:
    return load_prompt("system.md")
