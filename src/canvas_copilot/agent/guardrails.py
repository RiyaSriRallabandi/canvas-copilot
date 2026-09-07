"""Deterministic screen for "help me do my graded work" requests.

Layer 1 of the refusal boundary. It runs before the model and catches the
common direct and indirect forms. The system prompt is layer 2 (novel
phrasings), and the graph keeps a thread "blocked" once a request is caught so
follow-ups can't wear the model down over several turns.
"""

from __future__ import annotations

import re

_WORK = (
    r"(assignment|homework|hw|problem\s*set|pset|worksheet|lab|quiz|exam|midterm"
    r"|final|essay|paper|questions?|exercise|project|discussion(\s*post)?|response"
    r"|reflection|pset|deliverable)"
)

# Verb stems for "produce the work" — matches inflections (solve/solving/solved).
_MAKE = (
    r"(solv\w*|writ\w*|complet\w*|finish\w*|answer\w*|cod\w*|implement\w*|deriv\w*"
    r"|comput\w*|calculat\w*|develop\w*|draft\w*|creat\w*|build\w*|fill\s*out|fill\s*in)"
)

# "do" only as an imperative, not the auxiliary in "where do I ...".
_DO = r"do(?!\s+(?:i|you|we|they)\b)"

_PATTERNS = [
    # "<make-verb> ... <work>"  (article optional: "do the essay", "solve my pset", "do Bevel assignment")
    rf"\b(?:{_MAKE}|{_DO})\b[^.?!]{{0,50}}?\b{_WORK}\b",
    # "<work> ... for me / for us"
    rf"\b{_WORK}\b[^.?!]*\b(for me|for us)\b",
    # "help me / walk me through / guide me" + a piece of work or a solution
    rf"\b(walk me through|guide me through|talk me through)\b[^.?!]*\b({_WORK}|solution|answer)\b",
    # "help me [with] <make-verb>" — "help me develop the canvas", "help me write"
    rf"\bhelp me\b( with| on)?[^.?!]*\b(?:{_MAKE})\b",
    rf"\b(help me with|help me on)\b[^.?!]*\b{_WORK}\b",
    # "give me / tell me / show me ... the solution / answer"
    r"\b(give me|show me|tell me)\b[^.?!]*\b(solution|answer)s?\b",
    # "step by step" near a piece of work
    rf"\bstep[-\s]?by[-\s]?step\b[^.?!]*\b{_WORK}\b",
    rf"\b{_WORK}\b[^.?!]*\bstep[-\s]?by[-\s]?step\b",
    # "check / grade / verify my answer / work / solution / code"
    r"\b(check|grade|verify|correct|review)\b[^.?!]*\bmy\b[^.?!]*\b(answer|work|solution|code|submission)\b",
    r"\bis my (answer|solution|code|work|submission)\b[^.?!]*\b(right|correct|ok|good)\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]

# Lets the student pivot back to logistics after a block.
_LOGISTICS = re.compile(
    r"\b(due|deadline|submit|turn(\s*it)?\s*in|when|what time|where|which room|how "
    r"many points|worth|late policy|open until|lock|schedule|grade\b|midterm date"
    r"|exam date|office hours)\b",
    re.IGNORECASE,
)

REFUSAL = (
    "I can't help with completing, solving, drafting, or working through graded "
    "assignments — that's outside what Canvas Copilot does. I can tell you when "
    "it's due, how many points it's worth, whether you've submitted it, or point "
    "you to the assignment page."
)


def is_solve_request(text: str) -> bool:
    return any(p.search(text) for p in _COMPILED)


def is_logistics_question(text: str) -> bool:
    return bool(_LOGISTICS.search(text))
