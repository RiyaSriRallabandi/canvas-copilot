"""SQLite connection and schema management.

Schema changes are applied by an ordered list of migrations. ``PRAGMA
user_version`` records how many have run, so ``init_db`` is safe to call on
every startup and only applies what's new.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from platformdirs import user_data_dir

_APP_NAME = "canvas-copilot"

# Each entry is one migration, applied in order. Never edit or reorder an
# existing entry once it has shipped — append a new one instead.
_MIGRATIONS: list[str] = [
    """
    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE courses (
        id              INTEGER PRIMARY KEY,
        name            TEXT,
        course_code     TEXT,
        canvas_nickname TEXT
    );

    CREATE TABLE course_nicknames (
        phrase         TEXT PRIMARY KEY,   -- normalized lookup key
        display_phrase TEXT NOT NULL,      -- as the user typed it
        course_id      INTEGER NOT NULL,
        source         TEXT NOT NULL,      -- 'manual' | 'learned'
        created_at     TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE courses ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0;
    """,
]


def default_db_path() -> Path:
    directory = Path(user_data_dir(_APP_NAME))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "cache.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with sensible defaults and an initialized schema."""
    target = ":memory:" if path == ":memory:" else str(path or default_db_path())
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    applied = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, migration in enumerate(_MIGRATIONS[applied:], start=applied):
        conn.executescript(migration)
        conn.execute(f"PRAGMA user_version = {version + 1}")
    conn.commit()
