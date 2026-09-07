"""Turn Canvas HTML and PDF attachments into plain text."""

from __future__ import annotations

import io

import html2text
from pypdf import PdfReader
from pypdf.errors import PdfReadError

_H2T = html2text.HTML2Text()
_H2T.body_width = 0  # don't hard-wrap
_H2T.ignore_images = True
_H2T.ignore_emphasis = True
_H2T.single_line_break = True


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    return _H2T.handle(html).strip()


def pdf_to_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = (page.extract_text() or "" for page in reader.pages)
        return "\n\n".join(p.strip() for p in pages if p.strip()).strip()
    except (PdfReadError, ValueError, OSError):
        return ""
