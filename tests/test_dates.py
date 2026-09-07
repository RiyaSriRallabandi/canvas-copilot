"""Tests for relative-date resolution."""

from __future__ import annotations

from datetime import date

from canvas_copilot.agent.dates import hints_for, resolve_date_phrases

# 2026-09-09 is a Wednesday.
WED = date(2026, 9, 9)


def _labels(text: str) -> set[str]:
    return {r.label for r in resolve_date_phrases(text, WED)}


def test_today_and_tomorrow():
    ranges = {r.label: r for r in resolve_date_phrases("due today or tomorrow?", WED)}
    assert ranges["today"].start == WED == ranges["today"].end
    assert ranges["tomorrow"].start == date(2026, 9, 10)


def test_this_week_is_the_next_seven_days():
    (week,) = resolve_date_phrases("what's due this week", WED)
    assert week.start == WED
    assert week.end == date(2026, 9, 15)


def test_next_week_is_the_following_seven_days():
    (week,) = resolve_date_phrases("what's due next week", WED)
    assert week.start == date(2026, 9, 16)
    assert week.end == date(2026, 9, 22)


def test_next_week_wins_over_this_week():
    assert _labels("anything next week?") == {"next week"}


def test_weekend():
    (weekend,) = resolve_date_phrases("plans this weekend", WED)
    assert weekend.start == date(2026, 9, 12)  # Saturday
    assert weekend.end == date(2026, 9, 13)


def test_no_phrase_returns_nothing():
    assert resolve_date_phrases("do I have a midterm in stats", WED) == []


def test_hints_for_is_a_readable_string():
    assert hints_for("due today?", WED) == '"today" is 2026-09-09'
