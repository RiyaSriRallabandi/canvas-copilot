"""Resolve a free-text course reference to a specific Canvas course.

Order of preference:
    1. a stored nickname (manual or learned) that matches exactly
    2. an exact match on course code, official name, or Canvas nickname
    3. fuzzy matching, with a deliberately conservative bias toward asking

The thresholds below are first estimates; they get calibrated against real
course names and real phrasings in M7 (the eval harness).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from rapidfuzz import fuzz

from canvas_copilot.canvas.models import Course

if TYPE_CHECKING:
    from canvas_copilot.storage.nicknames import NicknameStore

_FILLER = {
    "my",
    "the",
    "a",
    "an",
    "class",
    "course",
    "section",
    "for",
    "in",
    "of",
    "to",
    "on",
    "with",
    "please",
}

# Fuzzy-match bands (0-100).
_AUTO_RESOLVE = 90  # a single match must beat this to resolve without asking
_GAP = 15  # ...and lead the runner-up by at least this much
_CONSIDER_FLOOR = 60  # below this, a course isn't a plausible match at all
_CLUSTER = 12  # matches within this of the top are "too close to call"

Status = Literal["resolved", "confirm", "ambiguous", "not_found"]


@dataclass
class Resolution:
    status: Status
    query: str
    course: Course | None = None
    candidates: list[Course] = field(default_factory=list)
    reason: str = ""
    # True when the match was found only by widening the search to past
    # (non-starred) courses.
    past_course: bool = False


def normalize(text: str) -> str:
    """Lowercase, drop punctuation (keeping hyphens), remove filler words."""
    lowered = re.sub(r"[^a-z0-9\s-]", " ", text.lower())
    words = [w for w in lowered.split() if w not in _FILLER]
    return " ".join(words).strip()


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _match_strings(course: Course) -> list[str]:
    """Full-string forms of a course's name/code/nickname, for fuzzy scoring."""
    parts = [course.name, course.course_code, course.nickname]
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        out.append(normalize(part))
        out.append(_alnum(part))
    return [s for s in out if s]


def _identifiers(course: Course) -> set[str]:
    """Short forms a student might type: whole words and acronyms.

    Acronyms cover the full name and its trailing 2- and 3-word tails, so
    "Introduction to Artificial Intelligence" yields "ai" (and "iai"), letting
    a query of "AI" match it even though the words never appear literally.
    """
    ids: set[str] = set()
    for part in (course.name, course.course_code, course.nickname):
        if not part:
            continue
        normalized = normalize(part)
        ids.add(normalized)
        ids.add(_alnum(part))

        tokens = normalized.split()
        ids.update(tokens)
        for tail in (tokens, tokens[-3:], tokens[-2:]):
            if len(tail) >= 2:
                ids.add("".join(word[0] for word in tail))
    return {i for i in ids if i}


def resolve_course(
    query: str,
    courses: list[Course],
    nicknames: NicknameStore | None = None,
    *,
    search_all: bool = False,
) -> Resolution:
    """Resolve within starred courses first, widening to all only on a miss.

    A match found only after widening is returned as ``confirm`` with
    ``past_course=True`` — never a silent ``resolved``.
    """
    favorites = [c for c in courses if c.is_favorite]
    use_favorites_only = bool(favorites) and not search_all
    pool = favorites if use_favorites_only else courses

    result = _resolve_within(query, pool, nicknames)
    if result.status != "not_found" or not use_favorites_only:
        return result
    if len(pool) == len(courses):
        return result

    widened = _resolve_within(query, courses, nicknames)
    if widened.status == "not_found":
        return widened

    favorite_ids = {c.id for c in favorites}
    if widened.course is not None and widened.course.id not in favorite_ids:
        widened.past_course = True
        if widened.status == "resolved":
            widened.status = "confirm"
    elif widened.status == "ambiguous" and all(
        c.id not in favorite_ids for c in widened.candidates
    ):
        widened.past_course = True
    return widened


def _resolve_within(
    query: str,
    courses: list[Course],
    nicknames: NicknameStore | None = None,
) -> Resolution:
    q = normalize(query)
    if not q:
        return Resolution("not_found", query, reason="empty query")

    by_id = {c.id: c for c in courses}

    # 1. stored nickname. A *learned* nickname (from a past clarification) only
    #    counts while its course is still current — otherwise it goes stale when
    #    the semester turns over. Manual nicknames are always honored.
    if nicknames is not None:
        entry = nicknames.get(query)
        if entry and entry.course_id in by_id:
            course = by_id[entry.course_id]
            stale = entry.source == "learned" and not course.is_favorite
            if not stale:
                return Resolution("resolved", query, course=course, reason="nickname")

    # 2. exact match on a word, acronym, code, or full name
    q_alnum = _alnum(query)
    exact = [
        c
        for c in courses
        if q in _identifiers(c) or (q_alnum and q_alnum in _identifiers(c))
    ]
    if len(exact) == 1:
        return Resolution("resolved", query, course=exact[0], reason="exact match")
    if len(exact) > 1:
        return Resolution(
            "ambiguous",
            query,
            candidates=exact,
            reason=f'"{query}" matches multiple courses',
        )

    # 3. fuzzy
    scored = sorted(
        (
            (c, max((fuzz.WRatio(q, s) for s in _match_strings(c)), default=0.0))
            for c in courses
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    plausible = [(c, s) for c, s in scored if s >= _CONSIDER_FLOOR]
    if not plausible:
        return Resolution("not_found", query, reason="no plausible match")

    top_course, top_score = plausible[0]
    runner_up = plausible[1][1] if len(plausible) > 1 else 0.0
    cluster = [c for c, s in plausible if top_score - s <= _CLUSTER]

    if len(cluster) >= 2:
        return Resolution(
            "ambiguous", query, candidates=cluster, reason=f"fuzzy {top_score:.0f}"
        )
    if top_score >= _AUTO_RESOLVE and top_score - runner_up >= _GAP:
        return Resolution(
            "resolved", query, course=top_course, reason=f"fuzzy {top_score:.0f}"
        )
    return Resolution(
        "confirm", query, course=top_course, reason=f"fuzzy {top_score:.0f}"
    )
