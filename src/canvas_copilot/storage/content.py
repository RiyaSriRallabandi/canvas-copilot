"""Stored, chunked course content (the text side; vectors are added in M2)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from canvas_copilot.content.chunk import Chunk


@dataclass(frozen=True)
class StoredChunk:
    id: int
    course_id: int
    source_type: str
    source_title: str | None
    source_url: str | None
    text: str


class ContentStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def replace_course(self, course_id: int, chunks: list[Chunk]) -> None:
        """Drop this course's chunks and write the fresh set."""
        now = datetime.now(UTC).isoformat()
        with self._conn:
            self._conn.execute(
                "DELETE FROM content_chunks WHERE course_id = ?", (course_id,)
            )
            self._conn.executemany(
                "INSERT INTO content_chunks (course_id, source_type, source_title, "
                "source_url, chunk_index, text, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.course_id,
                        c.source_type,
                        c.source_title,
                        c.source_url,
                        c.chunk_index,
                        c.text,
                        now,
                    )
                    for c in chunks
                ],
            )
            self._conn.execute(
                "INSERT INTO content_index_meta (course_id, indexed_at) VALUES (?, ?) "
                "ON CONFLICT(course_id) DO UPDATE SET indexed_at = excluded.indexed_at",
                (course_id, now),
            )

    def chunks_for(self, course_id: int) -> list[StoredChunk]:
        rows = self._conn.execute(
            "SELECT id, course_id, source_type, source_title, source_url, text "
            "FROM content_chunks WHERE course_id = ? ORDER BY id",
            (course_id,),
        ).fetchall()
        return [
            StoredChunk(
                id=r["id"],
                course_id=r["course_id"],
                source_type=r["source_type"],
                source_title=r["source_title"],
                source_url=r["source_url"],
                text=r["text"],
            )
            for r in rows
        ]

    def indexed_at(self, course_id: int) -> datetime | None:
        row = self._conn.execute(
            "SELECT indexed_at FROM content_index_meta WHERE course_id = ?",
            (course_id,),
        ).fetchone()
        return datetime.fromisoformat(row["indexed_at"]) if row else None
