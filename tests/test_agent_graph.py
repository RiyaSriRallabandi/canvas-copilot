"""Graph-wiring tests with a scripted chat model (no Ollama)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from canvas_copilot.agent.graph import build_agent
from canvas_copilot.agent.tools import AgentDeps
from canvas_copilot.canvas.models import Assignment, Course


class ScriptedModel(BaseChatModel):
    """Returns the next message from a fixed script on each call."""

    responses: list[BaseMessage]
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        message = self.responses[min(self._cursor, len(self.responses) - 1)]
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def _deps() -> tuple[AgentDeps, MagicMock]:
    client = MagicMock()
    client.list_courses.return_value = [
        Course(id=1, name="Stats", course_code="36-700", is_favorite=True)
    ]
    client.get_todo.return_value = [
        Assignment(id=7, name="Lab 3", course_id=1, html_url="http://x/7")
    ]
    cache = MagicMock()
    cache.get_courses.side_effect = lambda fetch, **kw: fetch()
    nicknames = MagicMock()
    return AgentDeps(client=client, cache=cache, nicknames=nicknames), client


def test_agent_calls_tool_then_answers():
    deps, client = _deps()
    model = ScriptedModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "get_todo", "args": {}, "id": "a"}]),
            AIMessage(content="You have **Lab 3** due."),
        ]
    )
    agent = build_agent(deps, model=model)
    result = agent.invoke({"messages": [("user", "what's due?")], "date_hints": ""})

    client.get_todo.assert_called_once()
    assert result["messages"][-1].content == "You have **Lab 3** due."


def test_bad_tool_args_are_reported_and_retried():
    deps, client = _deps()
    model = ScriptedModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "nonesuch", "args": {}, "id": "a"}]),
            AIMessage(content="Sorry, I could not look that up."),
        ]
    )
    agent = build_agent(deps, model=model)
    result = agent.invoke({"messages": [("user", "hi")], "date_hints": ""})

    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert "ERROR" in tool_msgs[0].content
    assert result["messages"][-1].content == "Sorry, I could not look that up."


def test_tool_loop_is_capped():
    deps, _ = _deps()
    # Always ask for a tool; the graph must still terminate with an answer.
    # Each AIMessage must be a distinct object with a unique id, or the
    # add_messages reducer treats repeats as edits to the same message.
    responses = [
        AIMessage(
            content="",
            id=f"call-{i}",
            tool_calls=[{"name": "get_todo", "args": {}, "id": f"t{i}"}],
        )
        for i in range(4)  # MAX_TOOL_TURNS
    ] + [AIMessage(content="done", id="final")]  # what `finalize` gets
    model = ScriptedModel(responses=responses)
    agent = build_agent(deps, model=model)
    result = agent.invoke({"messages": [("user", "loop")], "date_hints": ""})

    assert result["messages"][-1].content == "done"
    tool_turns = sum(1 for m in result["messages"] if m.type == "ai" and m.tool_calls)
    assert tool_turns == 4  # MAX_TOOL_TURNS
