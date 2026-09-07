"""The agent's read-only Canvas tools.

Built by :func:`build_tools` so each tool closes over a live ``AgentDeps``
(Canvas client + course cache + nickname store). Tools return plain strings —
the text the model reads back as the tool result.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

from langchain_core.tools import BaseTool, tool

from canvas_copilot.canvas.client import CanvasClient, CanvasReader
from canvas_copilot.canvas.models import Assignment, Course
from canvas_copilot.content.embed import Embedder
from canvas_copilot.content.search import Passage, search
from canvas_copilot.resolve import Resolution, normalize
from canvas_copilot.resolve import resolve_course as resolve_course_fn
from canvas_copilot.storage import CourseCache, NicknameStore
from canvas_copilot.storage.vectors import VectorStore


class NeedsClarification(Exception):
    """Raised by resolve_course when the student's reference is ambiguous.

    The graph's tool node catches this and routes to the ``clarify`` node,
    which asks the student to pick from ``candidates``.
    """

    def __init__(self, query: str, candidates: list[Course]) -> None:
        super().__init__(f"ambiguous course reference: {query!r}")
        self.query = query
        self.candidates = candidates


@dataclass
class AgentDeps:
    client: CanvasReader
    cache: CourseCache
    nicknames: NicknameStore
    # For content search: a DB connection and an embedder. None disables it.
    conn: sqlite3.Connection | None = None
    embedder: Embedder | None = None
    # Course picks made during THIS session (normalized phrase -> course id).
    # Populated when the student answers a clarification; not persisted.
    session_courses: dict[str, int] = field(default_factory=dict)
    # The last course successfully resolved this session, for "it" / "that class".
    last_course_id: int | None = None

    def courses(self) -> list[Course]:
        return self.cache.get_courses(self.client.list_courses)

    def resolve(self, query: str) -> Resolution:
        """Resolve a course reference, honoring this session's earlier picks."""
        key = normalize(query)
        course_id = self.session_courses.get(key)
        if course_id is not None:
            course = next((c for c in self.courses() if c.id == course_id), None)
            if course is not None:
                self.last_course_id = course.id
                return Resolution("resolved", query, course=course, reason="session")
        result = resolve_course_fn(query, self.courses(), self.nicknames)
        if result.status == "resolved" and result.course is not None:
            self.last_course_id = result.course.id
        return result

    def search_content(self, course_id: int, question: str) -> list[Passage] | None:
        """Passages from the course's indexed materials, or None if unavailable.

        Indexes the course now if it hasn't been indexed yet.
        """
        if self.conn is None or self.embedder is None:
            return None
        if not VectorStore(self.conn).has_course(course_id):
            if not isinstance(self.client, CanvasClient):
                return None
            from canvas_copilot.content.index import index_course

            index_course(self.client, self.conn, self.embedder, course_id)
        return search(self.conn, self.embedder, course_id, question)


def course_label(course: Course) -> str:
    return f"{course.nickname or course.name} [{course.course_code or '?'}]"


def format_resolution(result: Resolution) -> str:
    tag = " (a past course)" if result.past_course else ""
    if result.status == "resolved" and result.course:
        return f"RESOLVED: id {result.course.id} — {course_label(result.course)}{tag}"
    if result.status == "confirm" and result.course:
        return (
            f"UNCERTAIN: closest match is id {result.course.id} — "
            f"{course_label(result.course)}{tag}. Ask the student to confirm."
        )
    return (
        f'NOT_FOUND: no course matches "{result.query}". '
        "Tell the student and suggest they check the course name."
    )


def _parse_iso(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    moment = time(23, 59, 59) if end_of_day else time(0, 0)
    # Naive -> local-tz-aware, so day boundaries follow the student's timezone.
    return datetime.combine(date.fromisoformat(value), moment).astimezone()


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


def _fmt_due(assignment: Assignment) -> str:
    return "no due date" if assignment.due_at is None else _fmt_dt(assignment.due_at)


def _submission_note(a: Assignment) -> str | None:
    sub = a.submission
    if sub and sub.workflow_state == "graded":
        score = (
            f" ({sub.score:g}/{a.points_possible:g})"
            if (sub.score is not None and a.points_possible)
            else ""
        )
        return f"graded{score}"
    if sub and sub.is_submitted:
        return "submitted"
    if a.is_submittable_online:
        return "not submitted"
    return None


def _open_note(a: Assignment, *, now: datetime | None = None) -> str | None:
    now = now or datetime.now(UTC)
    if a.lock_at and now > a.lock_at:
        return f"closed {_fmt_dt(a.lock_at)}"
    if a.unlock_at and now < a.unlock_at:
        return f"opens {_fmt_dt(a.unlock_at)}"
    if a.lock_at:
        return f"open until {_fmt_dt(a.lock_at)}"
    return None


def _fmt_assignments(
    items: list[Assignment], course_label: dict[int, str] | None = None
) -> str:
    if not items:
        return "No assignments found."
    lines = []
    for a in items:
        link = f"[{a.name}]({a.html_url})" if a.html_url else a.name
        facts = [f"due {_fmt_due(a)}"]
        if a.points_possible:
            facts.append(f"{a.points_possible:g} pts")
        for note in (_submission_note(a), _open_note(a)):
            if note:
                facts.append(note)
        if course_label and a.course_id in course_label:
            facts.append(course_label[a.course_id])
        lines.append(f"- {link} — {' | '.join(facts)}")
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
        """Look up which specific course the student means by a name, nickname,
        or abbreviation — use this only to answer "which course is X" or to
        confirm a course exists. To get a course's assignments, use
        `course_assignments` instead. Pass the student's own words."""
        result = deps.resolve(query)
        if result.status == "ambiguous":
            raise NeedsClarification(query, result.candidates)
        return format_resolution(result)

    @tool
    def course_assignments(
        course_query: str,
        due_after: str | None = None,
        due_before: str | None = None,
    ) -> str:
        """Assignments for ONE course, each with its due date, points, submission
        status, and whether it is still open. Use this for anything about a
        course's assignments, homework, projects, quizzes, or exams — including
        "do I have a midterm", "is there a final", "how many points". `course_query`
        is the student's own words for the course. Optional `due_after` /
        `due_before` are ISO dates (YYYY-MM-DD) to limit to a window."""
        result = deps.resolve(course_query)
        if result.status == "ambiguous":
            raise NeedsClarification(course_query, result.candidates)
        if result.course is None:
            return format_resolution(result)
        assignments = deps.client.list_assignments(
            result.course.id,
            due_after=_parse_iso(due_after),
            due_before=_parse_iso(due_before, end_of_day=True),
        )
        header = f"{course_label(result.course)}:"
        past = " (this is a past course)" if result.past_course else ""
        return f"{header}{past}\n{_fmt_assignments(assignments)}"

    @tool
    def course_content(course_query: str, question: str) -> str:
        """Read ONE course's written material — syllabus, pages, announcements —
        to answer questions that are policy or prose. Use it for: the grading
        breakdown or late policy, the class time and room, office hours, the
        FORMAT of an exam (open book, length, Lockdown Browser), what a week's
        topic is. Also use it as a fallback for an exam date that isn't in
        `course_assignments`. For the list of assignments and their due dates,
        prefer `course_assignments`. `course_query` is the student's words for
        the course; `question` is what they want to know. Answer only from what
        this returns."""
        result = deps.resolve(course_query)
        if result.status == "ambiguous":
            raise NeedsClarification(course_query, result.candidates)
        if result.course is None:
            return format_resolution(result)

        passages = deps.search_content(result.course.id, question)
        if passages is None:
            return (
                f"{course_label(result.course)}: course materials aren't indexed. "
                "Tell the student to run `canvas-copilot index`."
            )
        if not passages:
            return (
                f"{course_label(result.course)}: nothing about that was found in "
                "the syllabus, pages, or announcements."
            )
        blocks = [f"{course_label(result.course)} — from the course materials:"]
        for p in passages:
            where = p.source_title or p.source_type
            link = f" — {p.source_url}" if p.source_url else ""
            blocks.append(f"\n[{where}{link}]\n{p.text}")
        return "\n".join(blocks)

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

    @tool
    def get_upcoming_events() -> str:
        """Upcoming events and assignment due dates across ALL the student's
        courses for roughly the next week. Use for "anything coming up",
        "upcoming quizzes", "what's this week" when no specific course is named."""
        events = deps.client.get_upcoming_events()
        if not events:
            return "Nothing coming up in the next week."
        lines = []
        for event in events:
            title = event.get("title") or "(untitled)"
            url = event.get("html_url", "")
            when = event.get("start_at") or (
                (event.get("assignment") or {}).get("due_at")
            )
            when_text = ""
            if when:
                try:
                    when_text = f" — {datetime.fromisoformat(when).astimezone():%a %b %d, %I:%M %p}"
                except ValueError:
                    when_text = ""
            context = event.get("context_name")
            suffix = f" ({context})" if context else ""
            link = f"[{title}]({url})" if url else title
            lines.append(f"- {link}{when_text}{suffix}")
        return "\n".join(lines)

    return [
        list_courses,
        resolve_course,
        course_assignments,
        course_content,
        get_todo,
        get_upcoming_events,
    ]
