"""Resolve relative date phrases to concrete ISO date ranges.

The 3B model is unreliable at date arithmetic (the M3 bake-off confirmed it), so
we detect common phrases before the model runs and hand it concrete dates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DateRange:
    label: str
    start: date
    end: date

    def as_hint(self) -> str:
        if self.start == self.end:
            return f'"{self.label}" is {self.start.isoformat()}'
        return f'"{self.label}" is {self.start.isoformat()} to {self.end.isoformat()}'




def resolve_date_phrases(text: str, today: date) -> list[DateRange]:
    """Return a DateRange for each recognized phrase in ``text`` (deduped)."""
    lowered = text.lower()
    found: list[DateRange] = []
    seen: set[str] = set()

    def add(candidate: DateRange) -> None:
        if candidate.label not in seen:
            seen.add(candidate.label)
            found.append(candidate)

    single = {
        "today": today,
        "tonight": today,
        "tomorrow": today + timedelta(days=1),
        "yesterday": today - timedelta(days=1),
    }
    for phrase, day in single.items():
        if re.search(rf"\b{phrase}\b", lowered):
            label = "today" if phrase == "tonight" else phrase
            add(DateRange(label, day, day))

    if re.search(r"\bnext week\b", lowered):
        add(DateRange("next week", today + timedelta(days=7), today + timedelta(days=13)))
    elif re.search(r"\b(this )?week\b", lowered):
        # "due this week" = the next 7 days (no weekday edge cases).
        add(DateRange("this week", today, today + timedelta(days=6)))

    if re.search(r"\bweekend\b", lowered):
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        add(DateRange("this weekend", saturday, saturday + timedelta(days=1)))

    return found


def hints_for(text: str, today: date) -> str:
    ranges = resolve_date_phrases(text, today)
    return "; ".join(r.as_hint() for r in ranges)


def primary_window(text: str, today: date) -> tuple[str, str] | None:
    """The first recognized date range as ISO strings, for injecting into tool
    calls when the model omits the dates. None if the question names no range.
    """
    ranges = resolve_date_phrases(text, today)
    if not ranges:
        return None
    first = ranges[0]
    return first.start.isoformat(), first.end.isoformat()
