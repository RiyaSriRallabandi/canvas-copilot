"""Retrieve the course-content chunks most relevant to a question.

Two rankers, fused. A vector search over the course's *guidance* text (syllabus,
pages, announcements, module outlines) handles paraphrase; a BM25 keyword search
over every chunk handles exact terms and reaches assignment text when a question
names something literally ("LockDown Browser"). Reciprocal-rank fusion merges
them, so a chunk both rankers like wins and neither ranker's blind spot is fatal.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from canvas_copilot.content.embed import Embedder
from canvas_copilot.storage.content import ContentStore, StoredChunk
from canvas_copilot.storage.vectors import VectorStore

# Types the vector ranker searches. Assignment descriptions are excluded here —
# they are dense with grading/points language that crowds out the syllabus on
# policy questions, and `course_assignments` already covers them directly — but
# they stay reachable through the keyword ranker below.
_GUIDANCE_TYPES = {"syllabus", "page", "announcement", "module"}

_POOL = 15  # candidates taken from each ranker before fusion
# Reciprocal-rank-fusion damping. The classic value is 60, tuned for long
# web-scale result lists; with pools of ~15 where we genuinely trust rank 0, a
# smaller constant lets the top of each list matter. The keyword ranker leads:
# for policy/prose questions the answer almost always contains the query's
# distinctive words, and BM25 separates them where a 768-dim embedding can't.
_RRF_C = 10
_KEYWORD_WEIGHT = 2.0
_VECTOR_WEIGHT = 1.0

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP_WORDS = (
    "the and are for how why what when where which who does did any all can could "
    "you your this that these those from with about into have has had was were will "
    "would should need needs give given tell find show list them they there here "
    "our their its required require use used using get please note also"
)
_STOP = frozenset(_STOP_WORDS.split())


@dataclass(frozen=True)
class Passage:
    text: str
    source_type: str
    source_title: str | None
    source_url: str | None
    score: float  # fused relevance, higher is better


def embed_course(conn: sqlite3.Connection, embedder: Embedder, course_id: int) -> int:
    """Embed a course's stored chunks and write their vectors. Returns the count."""
    chunks = ContentStore(conn).chunks_for(course_id)
    if not chunks:
        VectorStore(conn).replace_course(course_id, [])
        return 0
    vectors = embedder.embed_documents([c.text for c in chunks])
    VectorStore(conn).replace_course(
        course_id, list(zip((c.id for c in chunks), vectors, strict=True))
    )
    return len(chunks)


def _fts_query(question: str) -> str | None:
    terms = {w for w in _WORD.findall(question.lower()) if w not in _STOP}
    if not terms:
        return None
    return " OR ".join(sorted(f'"{t}"' for t in terms))


def _keyword_ranking(
    conn: sqlite3.Connection, course_id: int, question: str
) -> list[int]:
    query = _fts_query(question)
    if not query:
        return []
    rows = conn.execute(
        "SELECT chunk_id FROM content_fts "
        "WHERE course_id = ? AND content_fts MATCH ? "
        "ORDER BY bm25(content_fts) LIMIT ?",
        (course_id, query, _POOL),
    ).fetchall()
    return [r["chunk_id"] for r in rows]


def _vector_ranking(
    conn: sqlite3.Connection,
    embedder: Embedder,
    course_id: int,
    question: str,
    chunks: dict[int, StoredChunk],
) -> list[int]:
    hits = VectorStore(conn).search(
        course_id, embedder.embed_query(question), k=_POOL * 3
    )
    ranked = [
        chunk_id
        for chunk_id, _distance in hits
        if chunk_id in chunks and chunks[chunk_id].source_type in _GUIDANCE_TYPES
    ]
    return ranked[:_POOL]


def _fuse(keyword: list[int], vector: list[int], *, k: int) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for weight, ranking in ((_KEYWORD_WEIGHT, keyword), (_VECTOR_WEIGHT, vector)):
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (_RRF_C + rank + 1)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return ordered[:k]


def search(
    conn: sqlite3.Connection,
    embedder: Embedder,
    course_id: int,
    question: str,
    k: int = 3,
) -> list[Passage]:
    chunks = {c.id: c for c in ContentStore(conn).chunks_for(course_id)}
    if not chunks:
        return []
    keyword = _keyword_ranking(conn, course_id, question)
    vector = _vector_ranking(conn, embedder, course_id, question, chunks)
    passages = []
    for chunk_id, score in _fuse(keyword, vector, k=k):
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        passages.append(
            Passage(
                text=chunk.text,
                source_type=chunk.source_type,
                source_title=chunk.source_title,
                source_url=chunk.source_url,
                score=score,
            )
        )
    return passages
