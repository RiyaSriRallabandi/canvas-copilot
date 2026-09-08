"""Stored, chunked course content: the text and the keyword (FTS5) index.

Vectors live alongside in :mod:`canvas_copilot.storage.vectors`; the two are
written together by the indexer and fused at query time.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from canvas_copilot.content.chunk import Chunk

# Bumped whenever a change to chunking or ingestion means previously stored
# chunks should be rebuilt. `needs_reindex` compares this to what a course was
# last indexed under.
#   1 - initial
#   2 - smaller chunks, nomic task prefixes, hybrid keyword+vector retrieval
#   3 - link-only syllabi recorded as a URL; syllabus chunks carry a source link
CONTENT_SCHEMA = 3


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

    def replace_course(
        self,
        course_id: int,
        chunks: list[Chunk],
        *,
        external_syllabus_url: str | None = None,
    ) -> None:
        """Drop this course's chunks and write the fresh set (text + FTS + meta)."""
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
                "DELETE FROM content_fts WHERE course_id = ?", (course_id,)
            )
            stored = self._conn.execute(
                "SELECT id, text FROM content_chunks WHERE course_id = ? ORDER BY id",
                (course_id,),
            ).fetchall()
            self._conn.executemany(
                "INSERT INTO content_fts (text, chunk_id, course_id) VALUES (?, ?, ?)",
                [(r["text"], r["id"], course_id) for r in stored],
            )
            self._conn.execute(
                "INSERT INTO content_index_meta "
                "(course_id, indexed_at, external_syllabus_url, schema) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(course_id) DO UPDATE SET "
                "indexed_at = excluded.indexed_at, "
                "external_syllabus_url = excluded.external_syllabus_url, "
                "schema = excluded.schema",
                (course_id, now, external_syllabus_url, CONTENT_SCHEMA),
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

    def external_syllabus_url(self, course_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT external_syllabus_url FROM content_index_meta WHERE course_id = ?",
            (course_id,),
        ).fetchone()
        return row["external_syllabus_url"] if row else None

    def needs_reindex(self, course_id: int) -> bool:
        """True if the course has never been indexed or predates CONTENT_SCHEMA."""
        row = self._conn.execute(
            "SELECT schema FROM content_index_meta WHERE course_id = ?",
            (course_id,),
        ).fetchone()
        return row is None or row["schema"] < CONTENT_SCHEMA
