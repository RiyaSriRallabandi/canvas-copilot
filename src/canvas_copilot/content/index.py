"""Index one course end to end: fetch + chunk its content, then embed it.

The CLI's `index` command and the agent's lazy fallback both call this.
"""

from __future__ import annotations

import sqlite3

from canvas_copilot.canvas.client import CanvasClient
from canvas_copilot.content.embed import Embedder
from canvas_copilot.content.ingest import IngestResult, ingest_course
from canvas_copilot.content.search import embed_course
from canvas_copilot.storage.content import ContentStore


def index_course(
    client: CanvasClient,
    conn: sqlite3.Connection,
    embedder: Embedder,
    course_id: int,
) -> tuple[IngestResult, int]:
    """Returns (ingest counts, number of chunks embedded)."""
    result = ingest_course(client, course_id, ContentStore(conn))
    embedded = embed_course(conn, embedder, course_id)
    return result, embedded
