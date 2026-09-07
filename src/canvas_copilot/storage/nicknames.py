"""User-defined and auto-learned course nicknames.

``phrase`` is always the normalized form (see ``canvas_copilot.resolve.normalize``)
so lookups are case- and punctuation-insensitive. ``source`` distinguishes
nicknames the user set explicitly (``manual``) from ones learned when the user
answered a disambiguation prompt (``learned``).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

Source = str  # "manual" | "learned"  (a phrase -> course mapping; a course may have many)


@dataclass(frozen=True)
class Nickname:
    phrase: str
    display_phrase: str
    course_id: int
    source: Source
    created_at: datetime


class NicknameStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, phrase: str, course_id: int, *, source: Source = "manual") -> None:
        from canvas_copilot.resolve import normalize

        key = normalize(phrase)
        if not key:
            raise ValueError("nickname is empty after normalization")
        with self._conn:
            self._conn.execute(
                "INSERT INTO course_nicknames "
                "(phrase, display_phrase, course_id, source, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(phrase) DO UPDATE SET "
                "  display_phrase = excluded.display_phrase, "
                "  course_id = excluded.course_id, "
                "  source = excluded.source, "
                "  created_at = excluded.created_at",
                (
                    key,
                    phrase.strip(),
                    course_id,
                    source,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def learn(self, phrase: str, course_id: int) -> None:
        """Record a nickname discovered from a disambiguation answer.

        Never overwrites a manual nickname.
        """
        from canvas_copilot.resolve import normalize

        key = normalize(phrase)
        if not key:
            return
        existing = self.get(key)
        if existing and existing.source == "manual":
            return
        self.add(phrase, course_id, source="learned")

    def get(self, phrase: str) -> Nickname | None:
        from canvas_copilot.resolve import normalize

        row = self._conn.execute(
            "SELECT * FROM course_nicknames WHERE phrase = ?", (normalize(phrase),)
        ).fetchone()
        return self._row_to_nickname(row) if row else None

    def lookup(self, phrase: str) -> int | None:
        found = self.get(phrase)
        return found.course_id if found else None

    def remove(self, phrase: str) -> bool:
        from canvas_copilot.resolve import normalize

        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM course_nicknames WHERE phrase = ?", (normalize(phrase),)
            )
        return cur.rowcount > 0

    def list(self) -> list[Nickname]:
        rows = self._conn.execute(
            "SELECT * FROM course_nicknames ORDER BY display_phrase"
        ).fetchall()
        return [self._row_to_nickname(row) for row in rows]

    def prune_learned(self, keep_course_ids: set[int]) -> list[str]:
        """Delete auto-learned nicknames whose course is no longer in
        ``keep_course_ids``. Manual nicknames are left alone. Returns the
        display phrases removed.
        """
        rows = self._conn.execute(
            "SELECT display_phrase, phrase FROM course_nicknames "
            "WHERE source = 'learned' AND course_id NOT IN "
            f"({','.join('?' * len(keep_course_ids)) or 'NULL'})",
            tuple(keep_course_ids),
        ).fetchall()
        with self._conn:
            self._conn.executemany(
                "DELETE FROM course_nicknames WHERE phrase = ?",
                [(row["phrase"],) for row in rows],
            )
        return [row["display_phrase"] for row in rows]

    @staticmethod
    def _row_to_nickname(row: sqlite3.Row) -> Nickname:
        return Nickname(
            phrase=row["phrase"],
            display_phrase=row["display_phrase"],
            course_id=row["course_id"],
            source=row["source"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
