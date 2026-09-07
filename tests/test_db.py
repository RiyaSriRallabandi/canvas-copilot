"""Schema / migration tests."""

from __future__ import annotations

from canvas_copilot.storage.db import connect, init_db


def test_migrations_create_expected_tables():
    conn = connect(":memory:")
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"meta", "courses", "course_nicknames"} <= tables


def test_init_db_is_idempotent():
    conn = connect(":memory:")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    init_db(conn)
    init_db(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == version
