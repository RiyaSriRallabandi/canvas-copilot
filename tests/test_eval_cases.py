"""Validate the bundled bake-off cases (runs in CI; no Ollama needed)."""

from __future__ import annotations

from canvas_copilot.evals.cases import load_cases
from canvas_copilot.evals.tools import TOOL_NAMES


def test_cases_load_and_validate():
    cases = load_cases()
    assert len(cases) >= 10
    assert {c.id for c in cases if c.expect_refusal}  # at least one refusal probe


def test_every_accept_tool_is_real():
    for case in load_cases():
        assert set(case.accept_tools) <= TOOL_NAMES
