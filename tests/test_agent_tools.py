"""Tests for the agent's tools, with a mocked Canvas client."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from canvas_copilot.agent.tools import AgentDeps, NeedsClarification, build_tools
from canvas_copilot.canvas.models import Assignment, Course
from canvas_copilot.storage.db import connect
from canvas_copilot.storage.nicknames import NicknameStore

COURSES = [
    Course(id=1, name="AI Strategy", course_code="94-804", is_favorite=True),
    Course(id=2, name="Introduction to Artificial Intelligence", course_code="15-780", is_favorite=True),
    Course(id=3, name="Probability and Statistics", course_code="36-700", nickname="Stats", is_favorite=True),
]


@pytest.fixture
def tools():
    client = MagicMock()
    client.list_courses.return_value = COURSES
    cache = MagicMock()
    cache.get_courses.side_effect = lambda fetch, **kw: fetch()
    deps = AgentDeps(client=client, cache=cache, nicknames=NicknameStore(connect(":memory:")))
    return {t.name: t for t in build_tools(deps)}, client


def test_list_courses(tools):
    tool_map, _ = tools
    out = tool_map["list_courses"].invoke({})
    assert "AI Strategy" in out and "id 1" in out


def test_resolve_course_ambiguous_raises_for_clarification(tools):
    tool_map, _ = tools
    with pytest.raises(NeedsClarification) as excinfo:
        tool_map["resolve_course"].invoke({"query": "ai"})
    assert {c.id for c in excinfo.value.candidates} == {1, 2}


def test_resolve_course_resolved(tools):
    tool_map, _ = tools
    out = tool_map["resolve_course"].invoke({"query": "stats"})
    assert out.startswith("RESOLVED") and "id 3" in out


def test_course_assignments_resolves_course_and_formats_links(tools):
    tool_map, client = tools
    client.list_assignments.return_value = [
        Assignment(
            id=9,
            name="Problem Set 1",
            due_at=datetime(2026, 9, 12, 3, 59, tzinfo=timezone.utc),
            html_url="https://canvas.cmu.edu/courses/3/assignments/9",
        )
    ]
    out = tool_map["course_assignments"].invoke({"course_query": "stats"})
    # resolved to course id 3 internally
    assert client.list_assignments.call_args.args[0] == 3
    assert "[Problem Set 1](https://canvas.cmu.edu/courses/3/assignments/9)" in out


def test_course_assignments_ambiguous_raises(tools):
    tool_map, _ = tools
    with pytest.raises(NeedsClarification):
        tool_map["course_assignments"].invoke({"course_query": "ai"})


def test_course_assignments_passes_iso_window(tools):
    tool_map, client = tools
    client.list_assignments.return_value = []
    tool_map["course_assignments"].invoke(
        {"course_query": "stats", "due_after": "2026-09-09", "due_before": "2026-09-13"}
    )
    _, kwargs = client.list_assignments.call_args
    assert kwargs["due_after"].date().isoformat() == "2026-09-09"
    assert kwargs["due_before"].hour == 23


def test_get_todo_labels_courses(tools):
    tool_map, client = tools
    client.get_todo.return_value = [
        Assignment(
            id=5,
            name="Reading",
            course_id=1,
            due_at=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc),
            html_url="http://x/5",
        )
    ]
    out = tool_map["get_todo"].invoke({})
    assert "Reading" in out and "AI Strategy" in out


def test_get_todo_filters_by_due_window(tools):
    tool_map, client = tools
    client.get_todo.return_value = [
        Assignment(id=1, name="Past", due_at=datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)),
        Assignment(id=2, name="Today", due_at=datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)),
        Assignment(id=3, name="Later", due_at=datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)),
    ]
    out = tool_map["get_todo"].invoke(
        {"due_after": "2026-09-08", "due_before": "2026-09-12"}
    )
    assert "Today" in out
    assert "Past" not in out and "Later" not in out
