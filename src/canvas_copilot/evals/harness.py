"""Run eval scenarios against the real agent graph with canned Canvas data."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from canvas_copilot.agent.dates import hints_for, primary_window
from canvas_copilot.agent.graph import build_agent
from canvas_copilot.agent.tools import AgentDeps
from canvas_copilot.evals.fixtures import SEED_NICKNAMES, TODAY, FakeCanvasClient
from canvas_copilot.evals.scenarios import Scenario, Turn
from canvas_copilot.storage import CourseCache, NicknameStore, connect


@dataclass
class TurnTranscript:
    turn: Turn
    messages: list[AnyMessage]  # only the messages this turn produced


def build_eval_agent(
    *,
    model: BaseChatModel | None = None,
    model_name: str = "qwen2.5:3b",
    ollama_host: str = "http://localhost:11434",
):
    conn = connect(":memory:")
    nicknames = NicknameStore(conn)
    for phrase, course_id in SEED_NICKNAMES:
        nicknames.add(phrase, course_id, source="manual")
    deps = AgentDeps(FakeCanvasClient(), CourseCache(conn), nicknames)
    return build_agent(
        deps,
        model=model,
        model_name=model_name,
        ollama_host=ollama_host,
        today=TODAY,
        checkpointer=InMemorySaver(),
    )


def run_scenario(agent, scenario: Scenario) -> list[TurnTranscript]:
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    transcripts: list[TurnTranscript] = []

    for turn in scenario.turns:
        before = _thread_len(agent, config)
        state = agent.invoke(
            {
                "messages": [HumanMessage(content=turn.user)],
                "date_hints": hints_for(turn.user, TODAY),
                "date_window": primary_window(turn.user, TODAY),
                "clarify": None,
                "blocked": False,
            },
            config,
        )
        while state.get("__interrupt__"):
            options = state["__interrupt__"][0].value["options"]
            pick = turn.pick if turn.pick is not None else options[0]["id"]
            state = agent.invoke(Command(resume=pick), config)
        transcripts.append(TurnTranscript(turn, state["messages"][before:]))

    return transcripts


def _thread_len(agent, config) -> int:
    snapshot = agent.get_state(config)
    if not snapshot.values:
        return 0
    return len(snapshot.values.get("messages", []))
