"""Tests for content ingestion: cleaning, chunking, storing."""

from __future__ import annotations

from unittest.mock import MagicMock

from fpdf import FPDF

from canvas_copilot.canvas.models import (
    Announcement,
    Assignment,
    Module,
    ModuleItem,
    Page,
)
from canvas_copilot.content.chunk import chunk_text
from canvas_copilot.content.clean import html_to_text, pdf_to_text
from canvas_copilot.content.ingest import _find_syllabus_pdf, ingest_course
from canvas_copilot.storage.content import ContentStore
from canvas_copilot.storage.db import connect


def _pdf_bytes(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 10, text)
    return bytes(pdf.output())


# -- cleaning ---------------------------------------------------------


def test_html_to_text_keeps_structure_drops_markup():
    html = (
        "<h2>Grading</h2><p>Late work loses <b>10%</b> per day.</p><ul><li>PS1</li></ul>"
    )
    text = html_to_text(html)
    assert "Grading" in text
    assert "Late work loses 10% per day." in text
    assert "<" not in text


def test_html_to_text_handles_empty():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_pdf_to_text_extracts_words():
    text = pdf_to_text(_pdf_bytes("Office hours are Tuesdays at 3pm in GHC 4001"))
    assert "Office hours" in text and "GHC 4001" in text


def test_pdf_to_text_survives_garbage():
    assert pdf_to_text(b"not a pdf") == ""


# -- chunking -------------------------------------------------------


def test_chunk_text_splits_long_text_with_metadata():
    long_text = ("Section about attendance policy. " * 200).strip()
    chunks = chunk_text(
        long_text, course_id=7, source_type="syllabus", source_title="Syllabus"
    )
    assert len(chunks) > 1
    assert all(c.course_id == 7 and c.source_type == "syllabus" for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(len(c.text) <= 1700 for c in chunks)


def test_chunk_text_empty_returns_nothing():
    assert chunk_text("   ", course_id=1, source_type="page") == []


# -- syllabus-file heuristic ---------------------------------------


def test_find_syllabus_pdf():
    files = [
        {"display_name": "Lecture 1.pdf", "content-type": "application/pdf"},
        {"display_name": "Course Syllabus 2026.pdf", "content-type": "application/pdf"},
        {"display_name": "syllabus.docx", "content-type": "application/msword"},
    ]
    assert _find_syllabus_pdf(files)["display_name"] == "Course Syllabus 2026.pdf"
    assert _find_syllabus_pdf(files[:1]) is None


# -- ingest_course ------------------------------------------------


def test_ingest_course_pulls_every_source():
    client = MagicMock()
    client.get_syllabus.return_value = "<p>Grading: exams 60%, homework 40%.</p>"
    client.list_files.return_value = [
        {
            "display_name": "syllabus.pdf",
            "content-type": "application/pdf",
            "url": "http://f/1",
        }
    ]
    client.download_file.return_value = _pdf_bytes("Attendance is mandatory.")
    client.list_pages.return_value = [
        Page(url="week-1", title="Week 1", html_url="http://p/1")
    ]
    client.get_page.return_value = Page(
        url="week-1", title="Week 1", body="<p>Read chapter 2.</p>"
    )
    client.get_front_page.return_value = Page(
        url="home",
        title="Home",
        body="<p>Welcome. Class meets MWF.</p>",
        html_url="http://p/home",
    )
    client.list_modules.return_value = [
        Module(
            id=3,
            name="Week 3: Neural Networks",
            html_url="http://m/3",
            items=[
                ModuleItem(title="Backprop reading", type="Page"),
                ModuleItem(title="HW 3", type="Assignment"),
            ],
        )
    ]
    client.list_announcements.return_value = [
        Announcement(
            id=1,
            title="Room change",
            message="<p>We now meet in GHC 4401.</p>",
            html_url="http://a/1",
        )
    ]
    client.list_assignments.return_value = [
        Assignment(
            id=1,
            name="Project",
            description="<p>Use LockDown Browser.</p>",
            html_url="http://x/1",
        )
    ]

    store = ContentStore(connect(":memory:"))
    result = ingest_course(client, 7, store)

    assert result.counts["syllabus"] >= 2  # text field + PDF
    assert result.counts["page"] == 2  # front page + Week 1
    assert result.counts["module"] == 1
    assert result.counts["announcement"] == 1
    assert result.counts["assignment"] == 1

    stored = store.chunks_for(7)
    assert any("LockDown Browser" in c.text for c in stored)
    assert any("GHC 4401" in c.text for c in stored)
    assert any("Class meets MWF" in c.text for c in stored)
    module_chunk = next(c for c in stored if c.source_type == "module")
    assert "Neural Networks" in module_chunk.text and "HW 3" in module_chunk.text
    assert module_chunk.source_url == "http://m/3"
    assert store.indexed_at(7) is not None


def test_ingest_course_replaces_previous_chunks():
    client = MagicMock()
    client.get_syllabus.return_value = "<p>first version</p>"
    client.list_files.return_value = []
    client.list_pages.return_value = []
    client.get_front_page.return_value = None
    client.list_modules.return_value = []
    client.list_announcements.return_value = []
    client.list_assignments.return_value = []
    store = ContentStore(connect(":memory:"))

    ingest_course(client, 7, store)
    client.get_syllabus.return_value = "<p>second version</p>"
    ingest_course(client, 7, store)

    texts = " ".join(c.text for c in store.chunks_for(7))
    assert "second version" in texts and "first version" not in texts
