"""Multi-turn eval scenarios: load them, and score a transcript against them.

A scenario is a list of turns. Each turn has the student's message and an
``expect`` block of checks. Every check is pass/fail; a turn's score is the
fraction that passed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from langchain_core.messages import AIMessage, ToolMessage

_DIR = Path(__file__).parent / "cases"


@dataclass(frozen=True)
class Turn:
    user: str
    tools_called: tuple[str, ...] = ()          # required, as an ordered subsequence
    tools_not_called: tuple[str, ...] = ()
    tool_args: dict[str, dict[str, str]] = field(default_factory=dict)  # tool -> {arg_contains}
    answer_contains: tuple[str, ...] = ()
    answer_excludes: tuple[str, ...] = ()
    refused: bool = False
    pick: int | None = None                     # option id to choose if asked to clarify


@dataclass(frozen=True)
class Scenario:
    id: str
    turns: tuple[Turn, ...]


@dataclass
class CheckResult:
    label: str
    passed: bool
    detail: str = ""


def load_scenarios(path: Path | None = None) -> list[Scenario]:
    path = path or _DIR / "conversations.yaml"
    raw = yaml.safe_load(path.read_text())
    scenarios: list[Scenario] = []
    for item in raw:
        turns = tuple(
            Turn(
                user=t["user"],
                tools_called=tuple(t.get("tools_called", [])),
                tools_not_called=tuple(t.get("tools_not_called", [])),
                tool_args={k: v for k, v in (t.get("tool_args") or {}).items()},
                answer_contains=tuple(t.get("answer_contains", [])),
                answer_excludes=tuple(t.get("answer_excludes", [])),
                refused=bool(t.get("refused", False)),
                pick=t.get("pick"),
            )
            for t in item["turns"]
        )
        scenarios.append(Scenario(id=item["id"], turns=turns))
    _validate(scenarios)
    return scenarios


def _validate(scenarios: list[Scenario]) -> None:
    seen: set[str] = set()
    for s in scenarios:
        if s.id in seen:
            raise ValueError(f"duplicate scenario id: {s.id}")
        seen.add(s.id)
        if not s.turns:
            raise ValueError(f"{s.id}: no turns")


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(name in it for name in needle)


def score_turn(turn: Turn, turn_messages: list) -> list[CheckResult]:
    """Evaluate one turn's expectations against the messages it produced."""
    tool_calls = [
        call
        for m in turn_messages
        if isinstance(m, AIMessage)
        for call in (m.tool_calls or [])
    ]
    called_names = [c["name"] for c in tool_calls]
    answer = next(
        (m.content for m in reversed(turn_messages)
         if isinstance(m, AIMessage) and m.content),
        "",
    )
    results: list[CheckResult] = []

    if turn.refused:
        results.append(CheckResult(
            "refused: no tools called", not tool_calls,
            f"called {called_names}" if tool_calls else "",
        ))
        results.append(CheckResult(
            "refused: gave a response", bool(answer.strip()),
        ))

    if turn.tools_called:
        ok = _is_subsequence(list(turn.tools_called), called_names)
        results.append(CheckResult(
            f"tools called in order: {list(turn.tools_called)}", ok,
            f"got {called_names}",
        ))

    for name in turn.tools_not_called:
        results.append(CheckResult(
            f"tool NOT called: {name}", name not in called_names,
        ))

    for tool_name, arg_checks in turn.tool_args.items():
        matching = [c for c in tool_calls if c["name"] == tool_name]
        needle = arg_checks.get("arg_contains", "")
        blob = " ".join(
            str(v) for c in matching for v in (c.get("args") or {}).values()
        ).lower()
        results.append(CheckResult(
            f"{tool_name} arg contains {needle!r}",
            bool(matching) and needle.lower() in blob,
            f"args seen: {[c.get('args') for c in matching]}",
        ))

    for text in turn.answer_contains:
        results.append(CheckResult(
            f"answer contains {text!r}", text.lower() in answer.lower(),
        ))
    for text in turn.answer_excludes:
        results.append(CheckResult(
            f"answer excludes {text!r}", text.lower() not in answer.lower(),
        ))

    if not results:  # a turn with no explicit checks still must produce an answer
        results.append(CheckResult("produced an answer", bool(answer.strip())))
    return results


_PLACEHOLDER = re.compile(r"\[assignment name\]|\(url\)|<its name>|<its url>", re.I)


def universal_checks(answer: str) -> list[CheckResult]:
    """Checks applied to every turn's answer regardless of scenario."""
    return [
        CheckResult(
            "no placeholder text", not _PLACEHOLDER.search(answer or ""),
        )
    ]
