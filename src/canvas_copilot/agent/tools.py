"""The agent's read-only Canvas tools.

Built by :func:`build_tools` so each tool closes over a live ``AgentDeps``
(Canvas client + course cache + nickname store). Tools return plain strings —
the text the model reads back as the tool result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from langchain_core.tools import BaseTool, tool

from canvas_copilot.canvas.client import CanvasClient
from canvas_copilot.canvas.models import Assignment, Course
from canvas_copilot.resolve import resolve_course as resolve_course_fn
from canvas_copilot.storage import CourseCache, NicknameStore


@dataclass
class AgentDeps:
    client: CanvasClient
    cache: CourseCache
    nicknames: NicknameStore

    def courses(self) -> list[Course]:
        return self.cache.get_courses(self.client.list_courses)


def _parse_iso(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    moment = time(23, 59, 59) if end_of_day else time(0, 0)
    # Naive -> local-tz-aware, so day boundaries follow the student's timezone.
    return datetime.combine(date.fromisoformat(value), moment).astimezone()


def _fmt_due(assignment: Assignment) -> str:
    if assignment.due_at is None:
        return "no due date"
    return assignment.due_at.astimezone().strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


def _fmt_assignments(items: list[Assignment], course_label: dict[int, str] | None = None) -> str:
    if not items:
        return "No assignments found."
    lines = []
    for a in items:
        link = f"[{a.name}]({a.html_url})" if a.html_url else a.name
        suffix = ""
        if course_label and a.course_id in course_label:
            suffix = f" — {course_label[a.course_id]}"
        lines.append(f"- {link} — due {_fmt_due(a)}{suffix}")
    return "\n".join(lines)


def _fmt_courses(courses: list[Course]) -> str:
    if not courses:
        return "No courses found."
    return "\n".join(
        f"- id {c.id}: {c.nickname or c.name} [{c.course_code or '?'}]" for c in courses
    )


def build_tools(deps: AgentDeps) -> list[BaseTool]:
    @tool
    def list_courses() -> str:
        """List, show, or browse the student's courses. Use for any request to
        see their courses or classes ("what am I taking", "my classes this
        semester"). Not for looking up one specific course."""
        courses = deps.courses()
        current = [c for c in courses if c.is_favorite] or courses
        return _fmt_courses(current)

    @tool
    def resolve_course(query: str) -> str:
        """Identify ONE specific course the student named by title, nickname, or
        abbreviation (e.g. "Stats", "my AI class", "36-700"). Call this before
        any course-specific lookup to get the course id. The `query` argument is
        required and must be the student's own words for the course."""
        result = resolve_course_fn(query, deps.courses(), deps.nicknames)
        tag = " (a past course)" if result.past_course else ""
        if result.status == "resolved" and result.course:
            c = result.course
            return f"RESOLVED: id {c.id} — {c.nickname or c.name} [{c.course_code or '?'}]{tag}"
        if result.status == "confirm" and result.course:
            c = result.course
            return (
                f"UNCERTAIN: closest match is id {c.id} — {c.nickname or c.name}"
                f" [{c.course_code or '?'}]{tag}. Ask the student to confirm this is right."
            )
        if result.status == "ambiguous":
            opts = "\n".join(
                f"  - id {c.id}: {c.nickname or c.name} [{c.course_code or '?'}]"
                for c in result.candidates
            )
            return (
                f'AMBIGUOUS: "{query}" could mean several courses:\n{opts}\n'
                "Ask the student which one they mean and list these options. Do not guess."
            )
        return (
            f'NOT_FOUND: no course matches "{query}". '
            "Tell the student and suggest they check the course name."
        )

    @tool
    def get_assignments(
        course_id: int,
        due_after: str | None = None,
        due_before: str | None = None,
    ) -> str:
        """Get assignments for ONE course by its numeric id (from resolve_course
        or list_courses). Optionally filter to a due-date window with ISO dates
        (YYYY-MM-DD): due_after / due_before."""
        assignments = deps.client.list_assignments(
            course_id,
            due_after=_parse_iso(due_after),
            due_before=_parse_iso(due_before, end_of_day=True),
        )
        return _fmt_assignments(assignments)

    @tool
    def get_todo(due_after: str | None = None, due_before: str | None = None) -> str:
        """The student's Canvas to-do list: assignments across all courses that
        still need to be submitted. Best for "what's due", "what do I need to
        turn in", "what's next". For a specific day or range ("today", "this
        week"), pass due_after / due_before as ISO dates (YYYY-MM-DD) from the
        dates given in context."""
        items = deps.client.get_todo()
        after = _parse_iso(due_after)
        before = _parse_iso(due_before, end_of_day=True)
        if after is not None:
            items = [a for a in items if a.due_at and a.due_at >= after]
        if before is not None:
            items = [a for a in items if a.due_at and a.due_at <= before]
        labels = {c.id: (c.nickname or c.name or "") for c in deps.courses()}
        return _fmt_assignments(items, course_label=labels)

    return [list_courses, resolve_course, get_assignments, get_todo]
