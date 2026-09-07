"""Retrieve the course-content chunks most relevant to a question."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canvas_copilot.content.embed import Embedder
from canvas_copilot.storage.content import ContentStore
from canvas_copilot.storage.vectors import VectorStore


@dataclass(frozen=True)
class Passage:
    text: str
    source_type: str
    source_title: str | None
    source_url: str | None
    distance: float


def embed_course(conn: sqlite3.Connection, embedder: Embedder, course_id: int) -> int:
    """Embed a course's stored chunks and write their vectors. Returns the count."""
    chunks = ContentStore(conn).chunks_for(course_id)
    if not chunks:
        VectorStore(conn).replace_course(course_id, [])
        return 0
    vectors = embedder.embed([c.text for c in chunks])
    VectorStore(conn).replace_course(
        course_id, list(zip((c.id for c in chunks), vectors, strict=True))
    )
    return len(chunks)


def search(
    conn: sqlite3.Connection,
    embedder: Embedder,
    course_id: int,
    question: str,
    k: int = 6,
) -> list[Passage]:
    hits = VectorStore(conn).search(course_id, embedder.embed_one(question), k)
    if not hits:
        return []
    by_id = {c.id: c for c in ContentStore(conn).chunks_for(course_id)}
    passages = []
    for chunk_id, distance in hits:
        chunk = by_id.get(chunk_id)
        if chunk is None:
            continue
        passages.append(
            Passage(
                text=chunk.text,
                source_type=chunk.source_type,
                source_title=chunk.source_title,
                source_url=chunk.source_url,
                distance=distance,
            )
        )
    return passages
