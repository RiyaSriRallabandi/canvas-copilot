"""Deterministic pre-LLM screen for "do my graded work" requests.

The system prompt tells the model to refuse these, but a 3B model leaks under
rephrasing. This catches the common direct and indirect forms with plain
patterns before the agent runs at all — the prompt stays as the backstop for
novel phrasings.
"""

from __future__ import annotations

import re

_WORK = (
    r"(assignment|homework|hw|problem\s*set|pset|worksheet|lab|quiz|exam|midterm"
    r"|final|essay|paper|question|exercise|project|discussion(\s*post)?|response"
    r"|reflection)"
)
# "do" only counts as an imperative here — not the auxiliary in "where do I ...".
_DO = r"((?:do(?!\s+(?:i|you|we|they)\b))|write(\s*up)?|solve|complete|finish|answer|code|implement|derive|compute|calculate)"

_PATTERNS = [
    # "do / write / solve my homework", "complete this assignment for me"
    rf"\b{_DO}\b[^.?!]*\b(my|the|this|our)\b[^.?!]*\b{_WORK}\b",
    rf"\b{_WORK}\b[^.?!]*\b(for me|for us)\b",
    # "walk me through the solution", "give me the solution/answer"
    r"\b(walk me through|give me|show me|tell me)\b[^.?!]*\b(solution|answer)s?\b",
    # "step by step" tied to a piece of work
    rf"\bstep[-\s]?by[-\s]?step\b[^.?!]*\b{_WORK}\b",
    rf"\b{_WORK}\b[^.?!]*\bstep[-\s]?by[-\s]?step\b",
    # "is my answer right", "check my work/answer"
    r"\b(check|grade|verify|correct)\b[^.?!]*\bmy\b[^.?!]*\b(answer|work|solution|code)\b",
    r"\bis my (answer|solution|code|work)\b[^.?!]*\b(right|correct|ok)\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]

REFUSAL = (
    "I can't help with completing or solving graded work — that's outside what "
    "Canvas Copilot does. I can point you to the assignment page or relevant "
    "course materials if that helps."
)


def is_solve_request(text: str) -> bool:
    return any(p.search(text) for p in _COMPILED)
