"""Fixed, canned Canvas data for the evaluation harness.

Course names are the user's real starred courses (they don't change often).
Assignments, due dates, and events are invented and dated relative to
:data:`TODAY` (a Monday) so eval runs are fully deterministic.
``FakeCanvasClient`` stands in for the real client — no network, no token.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from canvas_copilot.canvas.models import Assignment, Course, User

TODAY = date(2026, 3, 16)  # Monday

# The nickname the user actually set (stored locally, not a Canvas nickname).
SEED_NICKNAMES = [("strategy", 55274)]


def _dt(day: int, month: int = 3, hour: int = 23, minute: int = 59) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


FAKE_USER = User(id=1, name="Test Student", primary_email="student@example.edu")

FAKE_COURSES = [
    Course(id=54550, name="2026 Career Academy", course_code="2026 Career Academy", is_favorite=True),
    Course(id=54829, name="Negotiation - C1", course_code="94800-C1", is_favorite=True),
    Course(id=55115, name="AIM Professional Seminar", course_code="95886-A", is_favorite=True),
    Course(id=55274, name="AI Strategy", course_code="94804", is_favorite=True),
    Course(id=55751, name="Introduction to Artificial Intelligence", course_code="95891", is_favorite=True),
    Course(
        id=56385,
        name="Making Products Count: Data Science for Product Managers - Fall 2026",
        course_code="95451",
        is_favorite=True,
    ),
    # A past (non-starred) course.
    Course(id=54095, name="OPTIONAL Introduction to Python Programming 2026",
           course_code="OPTIONAL Intro Python 2026", is_favorite=False),
]

_URL = "https://canvas.cmu.edu/courses/{c}/assignments/{a}"

FAKE_ASSIGNMENTS: dict[int, list[Assignment]] = {
    55274: [  # AI Strategy
        Assignment(id=1, course_id=55274, name="Company Selection Survey", due_at=_dt(11),
                   html_url=_URL.format(c=55274, a=1)),
        Assignment(id=2, course_id=55274, name="Canvas 1 Team Assignment", due_at=_dt(18),
                   html_url=_URL.format(c=55274, a=2)),
        Assignment(id=3, course_id=55274, name="Canvas 2 Team Assignment", due_at=_dt(4, month=4),
                   html_url=_URL.format(c=55274, a=3)),
    ],
    55751: [  # Introduction to Artificial Intelligence
        Assignment(id=4, course_id=55751, name="Worksheet 2", due_at=_dt(13),
                   html_url=_URL.format(c=55751, a=4)),
        Assignment(id=5, course_id=55751, name="Lab 5", due_at=_dt(19),
                   html_url=_URL.format(c=55751, a=5)),
        Assignment(id=6, course_id=55751, name="Homework 3", due_at=_dt(20),
                   html_url=_URL.format(c=55751, a=6)),
        Assignment(id=7, course_id=55751, name="Midterm Exam", due_at=_dt(25),
                   html_url=_URL.format(c=55751, a=7)),
    ],
    56385: [  # Making Products Count
        Assignment(id=8, course_id=56385, name="Python Proficiency Assessment", due_at=_dt(6),
                   html_url=_URL.format(c=56385, a=8)),
        Assignment(id=9, course_id=56385, name="HW 1 - CLV", due_at=_dt(22),
                   html_url=_URL.format(c=56385, a=9)),
    ],
    54829: [  # Negotiation
        Assignment(id=10, course_id=54829, name="Negotiation exercise #2", due_at=_dt(17),
                   html_url=_URL.format(c=54829, a=10)),
        Assignment(id=12, course_id=54829, name="Pre-class Reading", due_at=_dt(16, hour=17),
                   html_url=_URL.format(c=54829, a=12)),
    ],
    55115: [],
    54550: [],
    54095: [  # past course
        Assignment(id=11, course_id=54095, name="Python Basics Quiz", due_at=_dt(15, month=2),
                   html_url=_URL.format(c=54095, a=11)),
    ],
}

FAKE_TODO = [
    FAKE_ASSIGNMENTS[54829][1],  # Pre-class Reading - Mar 16
    FAKE_ASSIGNMENTS[54829][0],  # Negotiation exercise #2 - Mar 17
    FAKE_ASSIGNMENTS[55274][1],  # Canvas 1 Team Assignment - Mar 18
    FAKE_ASSIGNMENTS[55751][1],  # Lab 5 - Mar 19
    FAKE_ASSIGNMENTS[55751][2],  # Homework 3 - Mar 20
    FAKE_ASSIGNMENTS[56385][1],  # HW 1 - CLV - Mar 22
]

FAKE_UPCOMING = [
    {
        "title": "Midterm Exam",
        "html_url": _URL.format(c=55751, a=7),
        "start_at": "2026-03-25T18:00:00Z",
        "context_name": "Introduction to Artificial Intelligence",
        "type": "assignment",
    },
    {
        "title": "AI Strategy - Session B1",
        "html_url": "https://canvas.cmu.edu/calendar?event_id=99",
        "start_at": "2026-03-17T15:00:00Z",
        "context_name": "AI Strategy",
        "type": "event",
    },
]


class FakeCanvasClient:
    """Drop-in for CanvasClient backed by the canned data above."""

    def get_current_user(self) -> User:
        return FAKE_USER

    def list_courses(self, *, enrollment_state: str = "active") -> list[Course]:
        return list(FAKE_COURSES)

    def list_favorite_course_ids(self) -> set[int]:
        return {c.id for c in FAKE_COURSES if c.is_favorite}

    def list_course_nicknames(self):
        return []

    def list_assignments(self, course_id, *, due_after=None, due_before=None):
        items = list(FAKE_ASSIGNMENTS.get(course_id, []))
        if due_after is not None:
            items = [a for a in items if a.due_at and a.due_at >= due_after]
        if due_before is not None:
            items = [a for a in items if a.due_at and a.due_at <= due_before]
        return items

    def get_todo(self) -> list[Assignment]:
        return list(FAKE_TODO)

    def get_upcoming_events(self) -> list[dict]:
        return [dict(e) for e in FAKE_UPCOMING]

    def close(self) -> None:
        pass
