"""Vector search over content chunks, backed by the sqlite-vec extension.

The vec0 virtual table needs the extension loaded, which plain migrations can't
guarantee, so this module loads it and creates the table on first use.
"""

from __future__ import annotations

import sqlite3
import struct

import sqlite_vec

from canvas_copilot.content.embed import EMBED_DIM


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class VectorStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except AttributeError as exc:  # Python built without extension support
            raise RuntimeError(
                "This Python build can't load SQLite extensions, which vector "
                "search needs. Use a standard CPython build."
            ) from exc
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS content_vectors USING vec0("
            f"chunk_id INTEGER PRIMARY KEY, course_id INTEGER, "
            f"embedding FLOAT[{EMBED_DIM}] distance_metric=cosine)"
        )

    def replace_course(self, course_id: int, rows: list[tuple[int, list[float]]]) -> None:
        """rows: (chunk_id, embedding). Replaces this course's vectors."""
        with self._conn:
            self._conn.execute(
                "DELETE FROM content_vectors WHERE course_id = ?", (course_id,)
            )
            self._conn.executemany(
                "INSERT INTO content_vectors (chunk_id, course_id, embedding) "
                "VALUES (?, ?, ?)",
                [(chunk_id, course_id, _pack(vec)) for chunk_id, vec in rows],
            )

    def search(
        self, course_id: int, query_vector: list[float], k: int = 6
    ) -> list[tuple[int, float]]:
        """Return (chunk_id, distance) for the k closest chunks in the course."""
        rows = self._conn.execute(
            "SELECT chunk_id, distance FROM content_vectors "
            "WHERE course_id = ? AND embedding MATCH ? AND k = ? ORDER BY distance",
            (course_id, _pack(query_vector), k),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def has_course(self, course_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM content_vectors WHERE course_id = ? LIMIT 1", (course_id,)
        ).fetchone()
        return row is not None
