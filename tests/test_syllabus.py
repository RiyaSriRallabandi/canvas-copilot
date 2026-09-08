"""Tests for detecting a syllabus that lives outside Canvas."""

from __future__ import annotations

from canvas_copilot.content.syllabus import external_syllabus_url

_HOST = "canvas.cmu.edu"


def test_short_body_linking_out_returns_the_link():
    html = (
        "<p>Read the syllabus "
        '<a href="https://docs.google.com/document/d/abc123/edit">here</a>.</p>'
    )
    assert (
        external_syllabus_url(html, canvas_host=_HOST)
        == "https://docs.google.com/document/d/abc123/edit"
    )


def test_html_entities_in_the_href_are_decoded():
    html = (
        '<p>Syllabus: <a href="https://docs.google.com/document/d/x/edit?'
        'usp=sharing&amp;rtpof=true">link</a></p>'
    )
    assert external_syllabus_url(html, canvas_host=_HOST) == (
        "https://docs.google.com/document/d/x/edit?usp=sharing&rtpof=true"
    )


def test_substantial_body_is_not_treated_as_a_pointer():
    html = (
        "<p>"
        + "This course covers negotiation theory and practice. " * 40
        + ('</p><p><a href="https://example.com/extra">optional reading</a></p>')
    )
    assert external_syllabus_url(html, canvas_host=_HOST) is None


def test_internal_canvas_link_is_ignored():
    html = (
        '<p>See the <a href="https://canvas.cmu.edu/courses/1/pages/policies">'
        "policies page</a>.</p>"
    )
    assert external_syllabus_url(html, canvas_host=_HOST) is None


def test_empty_or_missing_body():
    assert external_syllabus_url(None, canvas_host=_HOST) is None
    assert external_syllabus_url("", canvas_host=_HOST) is None
    assert (
        external_syllabus_url("<p>No links here at all.</p>", canvas_host=_HOST) is None
    )
