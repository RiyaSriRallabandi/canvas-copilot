"""Detect a syllabus that lives outside Canvas.

Some courses put nothing in the Canvas syllabus field except a sentence linking
to a Google Doc or a course website. There is no institutional cooperation and
no fetching of external documents, so the right answer for those courses is the
link itself — not a guess assembled from whatever else got indexed.
"""

from __future__ import annotations

import html as _html
import re
from urllib.parse import urlparse

from canvas_copilot.content.clean import html_to_text

_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
# Above this many characters of visible text, treat the syllabus as real Canvas
# content even if it also links out.
_MAX_POINTER_CHARS = 500


def _domain(url: str | None) -> str:
    """Host of a URL, accepting a bare host, a `//host/…`, or a full URL."""
    if not url:
        return ""
    text = str(url).strip().lower()
    if "://" not in text and not text.startswith("//"):
        text = "//" + text
    try:
        return urlparse(text).netloc.split("@")[-1].split(":")[0]
    except ValueError:
        return ""


def external_syllabus_url(
    html: str | None, *, canvas_host: str | None = None
) -> str | None:
    """The off-Canvas URL a short, link-only syllabus points to, or None."""
    if not html:
        return None
    if len(html_to_text(html)) > _MAX_POINTER_CHARS:
        return None
    canvas_domain = _domain(canvas_host)
    for raw in _HREF.findall(html):
        link = _html.unescape(raw)
        host = _domain(link)
        if not host or not link.lower().startswith(("http://", "https://")):
            continue
        if canvas_domain and (
            host == canvas_domain or host.endswith("." + canvas_domain)
        ):
            continue
        if "instructure.com" in host:  # Canvas's own hosting
            continue
        return link
    return None
