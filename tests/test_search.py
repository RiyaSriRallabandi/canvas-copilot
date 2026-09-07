"""Tests for embedding, the vector store, and content search."""

from __future__ import annotations

import httpx
import pytest

from canvas_copilot.content.chunk import Chunk
from canvas_copilot.content.embed import EMBED_DIM, Embedder, EmbedError
from canvas_copilot.content.search import embed_course, search
from canvas_copilot.storage.content import ContentStore
from canvas_copilot.storage.db import connect
from canvas_copilot.storage.vectors import VectorStore

_VOCAB = ["late", "grade", "exam", "attendance", "lockdown", "office", "room"]


class FakeEmbedder:
    """A deterministic embedder: a dimension per keyword, so overlap ~ closeness."""

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * EMBED_DIM
        low = text.lower()
        for i, word in enumerate(_VOCAB):
            if word in low:
                v[i] = 1.0
        v[-1] = 0.01  # never all-zero
        return v

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


# -- Embedder (HTTP) ---------------------------------------------------


def _resp(url: str, payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


def test_embedder_batches_and_parses(monkeypatch):
    batch_sizes: list[int] = []

    def fake_post(url, json, timeout):
        n = len(json["input"])
        batch_sizes.append(n)
        return _resp(url, {"embeddings": [[0.0] * EMBED_DIM] * n})

    monkeypatch.setattr(httpx, "post", fake_post)
    out = Embedder(batch_size=2).embed_documents(["a", "b", "c"])
    assert len(out) == 3
    assert batch_sizes == [2, 1]


def test_embedder_raises_on_bad_response(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _resp("http://x/api/embed", {}))
    with pytest.raises(EmbedError):
        Embedder().embed_query("a")


# -- VectorStore -----------------------------------------------------


def test_vector_store_knn_and_course_filter():
    store = VectorStore(connect(":memory:"))
    store.replace_course(
        1,
        [
            (10, [1.0] + [0.0] * (EMBED_DIM - 1)),
            (11, [0.0, 1.0] + [0.0] * (EMBED_DIM - 2)),
        ],
    )
    store.replace_course(2, [(20, [1.0] + [0.0] * (EMBED_DIM - 1))])

    hits = store.search(1, [1.0] + [0.0] * (EMBED_DIM - 1), k=2)
    assert [h[0] for h in hits] == [10, 11]  # closest first
    assert all(h[0] != 20 for h in hits)  # course 2 excluded


def test_vector_store_replace_course_clears_old():
    store = VectorStore(connect(":memory:"))
    store.replace_course(1, [(10, [1.0] + [0.0] * (EMBED_DIM - 1))])
    store.replace_course(1, [(11, [1.0] + [0.0] * (EMBED_DIM - 1))])
    assert [h[0] for h in store.search(1, [1.0] + [0.0] * (EMBED_DIM - 1), k=5)] == [11]


# -- end to end ----------------------------------------------------


def test_embed_course_then_search_finds_the_right_passage():
    conn = connect(":memory:")
    ContentStore(conn).replace_course(
        7,
        [
            Chunk(
                7,
                "syllabus",
                "Grading",
                "http://s",
                0,
                "Late work loses 10% of the grade per day.",
            ),
            Chunk(
                7,
                "syllabus",
                "Attendance",
                "http://s",
                1,
                "Attendance is taken with in-class polls.",
            ),
            Chunk(
                7,
                "announcement",
                "Quiz",
                "http://a",
                0,
                "The quiz uses LockDown Browser in room GHC 4401.",
            ),
        ],
    )

    n = embed_course(conn, FakeEmbedder(), 7)
    assert n == 3

    results = search(conn, FakeEmbedder(), 7, "what is the late policy", k=2)
    assert results[0].text.startswith("Late work loses 10%")
    assert results[0].source_url == "http://s"

    lockdown = search(conn, FakeEmbedder(), 7, "do I need lockdown browser", k=1)
    assert "LockDown Browser" in lockdown[0].text


def test_search_returns_nothing_when_course_unindexed():
    conn = connect(":memory:")
    VectorStore(conn)  # create the table
    assert search(conn, FakeEmbedder(), 99, "anything") == []
