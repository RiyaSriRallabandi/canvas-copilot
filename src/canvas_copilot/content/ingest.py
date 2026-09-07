"""Fetch a course's unstructured content, clean it, chunk it, and store it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from canvas_copilot.canvas.client import CanvasClient, CanvasError
from canvas_copilot.content.chunk import Chunk, chunk_text
from canvas_copilot.content.clean import html_to_text, pdf_to_text
from canvas_copilot.storage.content import ContentStore

_SYLLABUS_FILE = re.compile(r"syllab", re.IGNORECASE)


@dataclass
class IngestResult:
    course_id: int
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def _add(self, source_type: str, chunks: list[Chunk]) -> list[Chunk]:
        self.counts[source_type] = self.counts.get(source_type, 0) + len(chunks)
        return chunks


def _find_syllabus_pdf(files: list[dict]) -> dict | None:
    for f in files:
        name = f.get("display_name") or f.get("filename") or ""
        is_pdf = f.get("content-type") == "application/pdf" or name.lower().endswith(
            ".pdf"
        )
        if is_pdf and _SYLLABUS_FILE.search(name):
            return f
    return None


def ingest_course(
    client: CanvasClient, course_id: int, store: ContentStore
) -> IngestResult:
    result = IngestResult(course_id)
    chunks: list[Chunk] = []

    chunks += result._add(
        "syllabus",
        chunk_text(
            html_to_text(client.get_syllabus(course_id)),
            course_id=course_id,
            source_type="syllabus",
            source_title="Syllabus",
        ),
    )

    try:
        pdf_file = _find_syllabus_pdf(client.list_files(course_id))
    except CanvasError:
        pdf_file = None  # some courses hide the Files tab
    if pdf_file and pdf_file.get("url"):
        text = pdf_to_text(client.download_file(pdf_file["url"]))
        chunks += result._add(
            "syllabus",
            chunk_text(
                text,
                course_id=course_id,
                source_type="syllabus",
                source_title=pdf_file.get("display_name", "Syllabus (PDF)"),
                source_url=pdf_file.get("url"),
            ),
        )

    try:
        pages = client.list_pages(course_id)
    except CanvasError:
        pages = []
    for summary in pages:
        page = client.get_page(course_id, summary.url)
        chunks += result._add(
            "page",
            chunk_text(
                html_to_text(page.body),
                course_id=course_id,
                source_type="page",
                source_title=page.title,
                source_url=page.html_url,
            ),
        )

    try:
        announcements = client.list_announcements(course_id)
    except CanvasError:
        announcements = []
    for ann in announcements:
        chunks += result._add(
            "announcement",
            chunk_text(
                html_to_text(ann.message),
                course_id=course_id,
                source_type="announcement",
                source_title=ann.title,
                source_url=ann.html_url,
            ),
        )

    for assignment in client.list_assignments(course_id):
        if assignment.description:
            chunks += result._add(
                "assignment",
                chunk_text(
                    html_to_text(assignment.description),
                    course_id=course_id,
                    source_type="assignment",
                    source_title=assignment.name,
                    source_url=assignment.html_url,
                ),
            )

    store.replace_course(course_id, chunks)
    return result
