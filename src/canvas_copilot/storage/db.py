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
    """
    CREATE TABLE content_chunks (
        id           INTEGER PRIMARY KEY,
        course_id    INTEGER NOT NULL,
        source_type  TEXT NOT NULL,      -- syllabus | page | announcement | assignment
        source_title TEXT,
        source_url   TEXT,
        chunk_index  INTEGER NOT NULL,
        text         TEXT NOT NULL,
        indexed_at   TEXT NOT NULL
    );
    CREATE INDEX ix_content_chunks_course ON content_chunks(course_id);

    CREATE TABLE content_index_meta (
        course_id  INTEGER PRIMARY KEY,
        indexed_at TEXT NOT NULL
    );
    """,
    # A keyword (BM25) index over the same chunks. Content search fuses this with
    # vector search, so an exact-term match ("Grade Breakdown") ranks well even
    # when the embedder can't separate it from its neighbours. `external_syllabus_url`
    # records a course whose syllabus is a link out of Canvas; `schema` lets the
    # indexer tell when stored chunks predate a chunking/retrieval change.
    """
    CREATE VIRTUAL TABLE content_fts USING fts5(
        text,
        chunk_id UNINDEXED,
        course_id UNINDEXED,
        tokenize = 'porter unicode61'
    );

    ALTER TABLE content_index_meta ADD COLUMN external_syllabus_url TEXT;
    ALTER TABLE content_index_meta ADD COLUMN schema INTEGER NOT NULL DEFAULT 1;
    """,
]


def default_db_path() -> Path:
    directory = Path(user_data_dir(_APP_NAME))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "cache.db"


def connect(
    path: Path | str | None = None, *, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open a connection with sensible defaults and an initialized schema.

    ``check_same_thread=False`` is for the web server, where FastAPI runs sync
    handlers on a threadpool; callers that pass it must serialize their own
    writes (the server holds one lock around agent turns).
    """
    target = ":memory:" if path == ":memory:" else str(path or default_db_path())
    conn = sqlite3.connect(target, check_same_thread=check_same_thread)
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
