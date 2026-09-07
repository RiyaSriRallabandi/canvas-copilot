"""Validate the eval scenarios and the scoring logic (CI-safe, no Ollama)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from canvas_copilot.evals.scenarios import (
    Turn,
    load_scenarios,
    score_turn,
    universal_checks,
)


def test_scenarios_load():
    scenarios = load_scenarios()
    assert len(scenarios) >= 12
    assert any(t.refused for s in scenarios for t in s.turns)


def test_score_turn_tool_order_and_answer():
    turn = Turn(
        user="x",
        tools_called=("course_assignments",),
        answer_contains=("Problem Set 6",),
        answer_excludes=("Assignment name",),
    )
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "course_assignments",
                    "args": {"course_query": "stats"},
                    "id": "1",
                }
            ],
        ),
        ToolMessage(content="- Problem Set 6", tool_call_id="1"),
        AIMessage(content="You have Problem Set 6 due."),
    ]
    results = score_turn(turn, messages)
    assert all(r.passed for r in results), [r.label for r in results if not r.passed]


def test_score_turn_flags_missing_tool_and_placeholder():
    turn = Turn(user="x", tools_called=("resolve_course",))
    messages = [AIMessage(content="Here it is: [Assignment name](url)")]
    results = score_turn(turn, messages) + universal_checks(messages[0].content)
    assert not all(r.passed for r in results)


def test_refused_turn_scoring():
    turn = Turn(user="solve it", refused=True)
    good = score_turn(turn, [AIMessage(content="I can't help with graded work.")])
    assert all(r.passed for r in good)
    bad = score_turn(
        turn,
        [
            AIMessage(
                content="", tool_calls=[{"name": "get_todo", "args": {}, "id": "1"}]
            ),
            AIMessage(content="Sure, here you go."),
        ],
    )
    assert not all(r.passed for r in bad)
