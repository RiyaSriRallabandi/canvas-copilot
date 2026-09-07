"""Tests for course resolution."""

from __future__ import annotations

from canvas_copilot.canvas.models import Course
from canvas_copilot.resolve import normalize, resolve_course
from canvas_copilot.storage.db import connect
from canvas_copilot.storage.nicknames import NicknameStore

COURSES = [
    Course(id=1, name="Introduction to Machine Learning", course_code="10-601"),
    Course(
        id=2,
        name="Probability and Statistics",
        course_code="36-700",
        nickname="Stats",
    ),
    Course(id=3, name="Human-Computer Interaction", course_code="05-610"),
]


def test_normalize_strips_filler_and_punctuation():
    assert normalize("My Stats class!") == "stats"
    assert normalize("the Intro to AI course") == "intro ai"


def test_exact_course_code_resolves():
    result = resolve_course("36-700", COURSES)
    assert result.status == "resolved"
    assert result.course is not None and result.course.id == 2


def test_canvas_nickname_resolves():
    result = resolve_course("stats", COURSES)
    assert result.status == "resolved"
    assert result.course is not None and result.course.id == 2


def test_strong_fuzzy_match_resolves_or_confirms():
    result = resolve_course("machine learning", COURSES)
    assert result.status in {"resolved", "confirm"}
    assert result.course is not None and result.course.id == 1


def test_two_close_matches_are_ambiguous():
    courses = [
        Course(id=1, name="Machine Learning"),
        Course(id=2, name="Deep Learning"),
        Course(id=3, name="Organic Chemistry"),
    ]
    result = resolve_course("learning", courses)
    assert result.status == "ambiguous"
    assert {c.id for c in result.candidates} == {1, 2}


def test_unrelated_query_is_not_found():
    result = resolve_course("astrophysics lab", COURSES)
    assert result.status == "not_found"


def test_acronym_resolves_to_single_course():
    result = resolve_course("ml", COURSES)
    assert result.status == "resolved"
    assert result.course is not None and result.course.id == 1


def test_acronym_shared_by_two_courses_is_ambiguous():
    courses = [
        Course(id=1, name="AI Strategy", course_code="94-804"),
        Course(
            id=2, name="Introduction to Artificial Intelligence", course_code="15-780"
        ),
        Course(id=3, name="Organic Chemistry", course_code="09-105"),
    ]
    result = resolve_course("ai", courses)
    assert result.status == "ambiguous"
    assert {c.id for c in result.candidates} == {1, 2}


def test_starred_courses_are_searched_first():
    courses = [
        Course(id=1, name="Machine Learning", is_favorite=True),
        Course(id=2, name="Machine Learning for Managers", is_favorite=False),
    ]
    result = resolve_course("machine learning", courses)
    assert result.status == "resolved"
    assert result.course is not None and result.course.id == 1
    assert result.past_course is False


def test_past_course_match_is_a_confirm():
    courses = [
        Course(id=1, name="Probability and Statistics", is_favorite=True),
        Course(
            id=2, name="Introduction to Java", course_code="15-121", is_favorite=False
        ),
    ]
    result = resolve_course("java", courses)
    assert result.status == "confirm"
    assert result.past_course is True
    assert result.course is not None and result.course.id == 2


def test_search_all_includes_past_courses_directly():
    courses = [
        Course(id=1, name="Probability and Statistics", is_favorite=True),
        Course(
            id=2, name="Introduction to Java", course_code="15-121", is_favorite=False
        ),
    ]
    result = resolve_course("java", courses, search_all=True)
    assert result.status == "resolved"
    assert result.course is not None and result.course.id == 2


def test_manual_nickname_overrides_acronym_ambiguity():
    courses = [
        Course(id=1, name="AI Strategy"),
        Course(id=2, name="Introduction to Artificial Intelligence"),
    ]
    nicknames = NicknameStore(connect(":memory:"))
    nicknames.add("ai", 1)
    result = resolve_course("ai", courses, nicknames)
    assert result.status == "resolved"
    assert result.course is not None and result.course.id == 1


def test_stale_learned_nickname_is_ignored():
    nicknames = NicknameStore(connect(":memory:"))
    nicknames.learn("ai", 99)  # a course that is no longer current
    courses = [
        Course(id=1, name="Advanced AI Systems", course_code="17-737", is_favorite=True),
        Course(id=99, name="Old Intro to AI", is_favorite=False),
    ]
    result = resolve_course("ai", courses, nicknames)
    assert result.status == "resolved"
    assert result.course is not None and result.course.id == 1


def test_manual_nickname_to_past_course_still_finds_it():
    nicknames = NicknameStore(connect(":memory:"))
    nicknames.add("thesis", 99, source="manual")
    courses = [
        Course(id=1, name="Statistics", is_favorite=True),
        Course(id=99, name="Thesis Research", is_favorite=False),
    ]
    result = resolve_course("thesis", courses, nicknames)
    assert result.course is not None and result.course.id == 99


def test_stored_nickname_wins():
    nicknames = NicknameStore(connect(":memory:"))
    nicknames.add("hci", 3)
    result = resolve_course("hci", COURSES, nicknames)
    assert result.status == "resolved"
    assert result.course is not None and result.course.id == 3
    assert result.reason == "nickname"
