"""Fetch a course's unstructured content, clean it, chunk it, and store it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from canvas_copilot.canvas.client import CanvasClient, CanvasError
from canvas_copilot.content.chunk import Chunk, chunk_text
from canvas_copilot.content.clean import html_to_text, pdf_to_text
from canvas_copilot.content.syllabus import external_syllabus_url
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

    try:
        web_base = client.web_base_url
    except Exception:  # noqa: BLE001 - a bad base URL shouldn't stop ingestion
        web_base = None
    raw_syllabus = client.get_syllabus(course_id)
    external_url = external_syllabus_url(raw_syllabus, canvas_host=web_base)
    if not external_url:
        # A link-only syllabus ("read it here: <google doc>") is noise once the
        # link is captured in meta; only chunk a syllabus that has real prose.
        syllabus_url = (
            f"{web_base}/courses/{course_id}/assignments/syllabus" if web_base else None
        )
        chunks += result._add(
            "syllabus",
            chunk_text(
                html_to_text(raw_syllabus),
                course_id=course_id,
                source_type="syllabus",
                source_title="Syllabus",
                source_url=syllabus_url,
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
    seen_pages = {p.url for p in pages}
    front = client.get_front_page(course_id)
    if front and front.url not in seen_pages:
        pages = [front, *pages]
    for summary in pages:
        body = (
            summary.body
            if summary.body is not None
            else (client.get_page(course_id, summary.url).body)
        )
        chunks += result._add(
            "page",
            chunk_text(
                html_to_text(body),
                course_id=course_id,
                source_type="page",
                source_title=summary.title,
                source_url=summary.html_url,
            ),
        )

    try:
        modules = client.list_modules(course_id)
    except CanvasError:
        modules = []
    for module in modules:
        lines = [module.name or "Module"]
        lines += [
            f"- {item.title}" + (f" ({item.type})" if item.type else "")
            for item in module.items
            if item.title
        ]
        if len(lines) > 1:
            chunks += result._add(
                "module",
                chunk_text(
                    "\n".join(lines),
                    course_id=course_id,
                    source_type="module",
                    source_title=module.name,
                    source_url=module.html_url,
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

    store.replace_course(course_id, chunks, external_syllabus_url=external_url)
    return result
