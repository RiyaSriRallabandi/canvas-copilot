"""Cached access to the Canvas course list.

The course list changes rarely, so we store it locally and only re-fetch when
it is older than ``max_age`` (or when forced). This keeps us well clear of the
Canvas API rate limit during normal use.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from canvas_copilot.canvas.models import Course

_SYNCED_AT_KEY = "courses_synced_at"
_DEFAULT_MAX_AGE = timedelta(hours=24)

CourseFetcher = Callable[[], list[Course]]


class CourseCache:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_courses(
        self,
        fetch: CourseFetcher,
        *,
        max_age: timedelta = _DEFAULT_MAX_AGE,
        force: bool = False,
    ) -> list[Course]:
        if force or self._is_stale(max_age):
            self._store(fetch())
        return self._load()

    def refresh(self, fetch: CourseFetcher) -> list[Course]:
        self._store(fetch())
        return self._load()

    def synced_at(self) -> datetime | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (_SYNCED_AT_KEY,)
        ).fetchone()
        return datetime.fromisoformat(row["value"]) if row else None

    # -- internals ------------------------------------------------------

    def _is_stale(self, max_age: timedelta) -> bool:
        synced = self.synced_at()
        if synced is None:
            return True
        return datetime.now(timezone.utc) - synced > max_age

    def _store(self, courses: list[Course]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM courses")
            self._conn.executemany(
                "INSERT INTO courses "
                "(id, name, course_code, canvas_nickname, is_favorite) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (c.id, c.name, c.course_code, c.nickname, int(c.is_favorite))
                    for c in courses
                ],
            )
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_SYNCED_AT_KEY, datetime.now(timezone.utc).isoformat()),
            )

    def _load(self) -> list[Course]:
        rows = self._conn.execute(
            "SELECT id, name, course_code, canvas_nickname, is_favorite "
            "FROM courses ORDER BY id"
        ).fetchall()
        return [
            Course(
                id=row["id"],
                name=row["name"],
                course_code=row["course_code"],
                nickname=row["canvas_nickname"],
                is_favorite=bool(row["is_favorite"]),
            )
            for row in rows
        ]
