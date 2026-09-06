"""Load and validate bake-off eval cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from canvas_copilot.evals.tools import TOOL_NAMES

_CASES_DIR = Path(__file__).parent / "cases"


@dataclass(frozen=True)
class Case:
    id: str
    query: str
    accept_tools: tuple[str, ...] = ()
    # For the chosen tool, require one of its string args to contain a substring
    # (case-insensitive). e.g. {"query": "stat"} for resolve_course.
    arg_contains: dict[str, str] = field(default_factory=dict)
    expect_refusal: bool = False


def load_cases(path: Path | None = None) -> list[Case]:
    path = path or _CASES_DIR / "tool_selection.yaml"
    raw = yaml.safe_load(path.read_text())
    cases = [
        Case(
            id=item["id"],
            query=item["query"],
            accept_tools=tuple(item.get("accept_tools", [])),
            arg_contains=item.get("arg_contains", {}) or {},
            expect_refusal=bool(item.get("expect_refusal", False)),
        )
        for item in raw
    ]
    _validate(cases)
    return cases


def _validate(cases: list[Case]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case id: {case.id}")
        seen.add(case.id)
        if case.expect_refusal:
            if case.accept_tools:
                raise ValueError(f"{case.id}: refusal case must not list accept_tools")
            continue
        if not case.accept_tools:
            raise ValueError(f"{case.id}: needs accept_tools or expect_refusal")
        unknown = set(case.accept_tools) - TOOL_NAMES
        if unknown:
            raise ValueError(f"{case.id}: unknown tool(s) {sorted(unknown)}")
