"""Stub tool definitions for the bake-off.

These are the tools the M4 agent will expose, with the same names, signatures,
and descriptions — but here they do nothing. The bake-off only measures which
tool the model picks and with what arguments, not the tool's output.
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def list_courses() -> str:
    """List, show, or browse the student's courses. Use for any request to see
    their courses or classes ("what am I taking", "my classes this semester").
    Not for looking up one specific course."""
    return ""


@tool
def resolve_course(query: str) -> str:
    """Identify ONE specific course the student named by title, nickname, or
    abbreviation (e.g. "Stats", "my AI class", "36-700"). Call this before any
    course-specific lookup to get the course id. The `query` argument is
    required and must be the student's own words for the course."""
    return ""


@tool
def get_assignments(
    course_id: int,
    due_after: str | None = None,
    due_before: str | None = None,
) -> str:
    """Get assignments for one course. Optionally filter to a due-date window
    given as ISO 8601 dates (YYYY-MM-DD)."""
    return ""


@tool
def get_todo() -> str:
    """Get the student's Canvas to-do list: upcoming assignments that still need
    to be submitted, across all courses."""
    return ""


@tool
def get_upcoming_events() -> str:
    """Get the student's upcoming events and assignment due dates for the next
    week, across all courses."""
    return ""


@tool
def get_calendar_events(start_date: str, end_date: str) -> str:
    """Get calendar events (exams, quizzes, review sessions) between two ISO 8601
    dates (YYYY-MM-DD)."""
    return ""


ALL_TOOLS = [
    list_courses,
    resolve_course,
    get_assignments,
    get_todo,
    get_upcoming_events,
    get_calendar_events,
]

TOOL_NAMES = {t.name for t in ALL_TOOLS}
