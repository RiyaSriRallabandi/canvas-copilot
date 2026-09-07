"""Split cleaned text into overlapping chunks with their source metadata."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

# ~200 tokens per chunk, ~40 of overlap. Small chunks keep a passage on one
# topic, which matters for retrieval. Split on structure first (markdown
# headings from html2text), then paragraphs, then sentences.
_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=160,
    separators=["\n# ", "\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""],
)


@dataclass(frozen=True)
class Chunk:
    course_id: int
    source_type: str  # "syllabus" | "page" | "announcement" | "assignment"
    source_title: str | None
    source_url: str | None
    chunk_index: int
    text: str


def chunk_text(
    text: str,
    *,
    course_id: int,
    source_type: str,
    source_title: str | None = None,
    source_url: str | None = None,
) -> list[Chunk]:
    cleaned = text.strip()
    if not cleaned:
        return []
    pieces = [p.strip() for p in _SPLITTER.split_text(cleaned) if p.strip()]
    return [
        Chunk(course_id, source_type, source_title, source_url, i, piece)
        for i, piece in enumerate(pieces)
    ]
