"""Tests for the TTL course cache."""

from __future__ import annotations

from datetime import timedelta

from canvas_copilot.canvas.models import Course
from canvas_copilot.storage.cache import CourseCache
from canvas_copilot.storage.db import connect


def _courses(*ids: int) -> list[Course]:
    return [Course(id=i, name=f"Course {i}", course_code=f"C{i}") for i in ids]


def test_fetches_once_then_serves_from_cache():
    cache = CourseCache(connect(":memory:"))
    calls: list[int] = []

    def fetch() -> list[Course]:
        calls.append(1)
        return _courses(1, 2)

    assert [c.id for c in cache.get_courses(fetch)] == [1, 2]
    assert [c.id for c in cache.get_courses(fetch)] == [1, 2]
    assert len(calls) == 1


def test_refetches_when_stale():
    cache = CourseCache(connect(":memory:"))
    calls: list[int] = []

    def fetch() -> list[Course]:
        calls.append(1)
        return _courses(1)

    cache.get_courses(fetch)
    cache.get_courses(fetch, max_age=timedelta(seconds=-1))
    assert len(calls) == 2


def test_force_bypasses_cache():
    cache = CourseCache(connect(":memory:"))
    calls: list[int] = []

    def fetch() -> list[Course]:
        calls.append(1)
        return _courses(1)

    cache.get_courses(fetch)
    cache.get_courses(fetch, force=True)
    assert len(calls) == 2


def test_round_trips_canvas_nickname_and_favorite_flag():
    cache = CourseCache(connect(":memory:"))
    courses = [
        Course(id=3, name="Statistics", course_code="36-700", nickname="Stats", is_favorite=True),
        Course(id=4, name="Old Course", is_favorite=False),
    ]
    result = {c.id: c for c in cache.get_courses(lambda: courses)}
    assert result[3].nickname == "Stats"
    assert result[3].is_favorite is True
    assert result[4].is_favorite is False
