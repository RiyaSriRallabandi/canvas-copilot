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


def _deps(courses: list[Course] | None = None) -> tuple[AgentDeps, MagicMock]:
    client = MagicMock()
    client.list_courses.return_value = courses or [
        Course(id=1, name="Stats", course_code="36-700", is_favorite=True)
    ]
    client.get_todo.return_value = [
        Assignment(id=7, name="Lab 3", course_id=1, html_url="http://x/7")
    ]
    client.list_assignments.return_value = []
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


def test_explicit_course_phrase_overrides_the_models_guess():
    courses = [
        Course(id=10, name="AI Strategy", is_favorite=True),
        Course(id=20, name="Introduction to Artificial Intelligence", is_favorite=True),
    ]
    deps, client = _deps(courses)
    model = ScriptedModel(responses=[
        AIMessage(content="", id="c1", tool_calls=[
            {"name": "course_assignments", "args": {"course_query": "AI Strategy"}, "id": "g1"}
        ]),
        AIMessage(content="done", id="c2"),
    ])
    agent = build_agent(deps, model=model)
    agent.invoke({
        "messages": [("user", "what is due in Introduction to Artificial Intelligence?")],
        "date_hints": "", "date_window": None, "clarify": None,
    })
    # model said "AI Strategy" (10); the student's words win -> course 20
    assert client.list_assignments.call_args.args[0] == 20


def test_pronoun_followup_uses_the_last_resolved_course():
    from langgraph.checkpoint.memory import InMemorySaver

    courses = [
        Course(id=10, name="AI Strategy", is_favorite=True),
        Course(id=20, name="Introduction to Artificial Intelligence", is_favorite=True),
    ]
    deps, client = _deps(courses)
    model = ScriptedModel(responses=[
        AIMessage(content="", id="a1", tool_calls=[
            {"name": "course_assignments",
             "args": {"course_query": "Introduction to Artificial Intelligence"}, "id": "g1"}
        ]),
        AIMessage(content="ok", id="a2"),
        AIMessage(content="", id="a3", tool_calls=[
            {"name": "course_assignments", "args": {"course_query": "AI Strategy"}, "id": "g2"}
        ]),
        AIMessage(content="ok2", id="a4"),
    ])
    agent = build_agent(deps, model=model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    agent.invoke({"messages": [("user", "assignments in Introduction to Artificial Intelligence?")],
                  "date_hints": "", "date_window": None, "clarify": None}, config)
    agent.invoke({"messages": [("user", "does it have a final exam?")],
                  "date_hints": "", "date_window": None, "clarify": None}, config)
    # "it" -> the last course (20), not the model's "AI Strategy" (10)
    assert client.list_assignments.call_args.args[0] == 20


def test_solve_request_is_refused_before_the_model_runs():
    deps, client = _deps()
    model = ScriptedModel(responses=[AIMessage(content="should not be reached")])
    agent = build_agent(deps, model=model)
    result = agent.invoke({
        "messages": [("user", "write the code for my homework for me")],
        "date_hints": "", "date_window": None, "clarify": None,
    })
    answer = result["messages"][-1].content
    assert "can't help" in answer.lower()
    client.get_todo.assert_not_called()
    client.list_assignments.assert_not_called()


def test_course_assignments_injects_the_date_window():
    deps, client = _deps([Course(id=7, name="Stats", nickname="Stats", is_favorite=True)])
    model = ScriptedModel(
        responses=[
            AIMessage(
                content="", id="c1",
                tool_calls=[{"name": "course_assignments",
                             "args": {"course_query": "stats"}, "id": "g1"}],
            ),
            AIMessage(content="Here you go.", id="c2"),
        ]
    )
    agent = build_agent(deps, model=model)
    agent.invoke({
        "messages": [("user", "what's due this week in stats?")],
        "date_hints": "",
        "date_window": ("2026-03-16", "2026-03-22"),
        "clarify": None,
    })
    # the model omitted the dates; the graph injected them
    _, kwargs = client.list_assignments.call_args
    assert kwargs["due_after"].date().isoformat() == "2026-03-16"


def test_conversation_remembers_the_resolved_course_across_turns():
    from langgraph.checkpoint.memory import InMemorySaver

    deps, client = _deps([Course(id=7, name="Stats", nickname="Stats", is_favorite=True)])
    model = ScriptedModel(
        responses=[
            AIMessage(
                content="", id="a1",
                tool_calls=[{"name": "course_assignments",
                             "args": {"course_query": "stats"}, "id": "g1"}],
            ),
            AIMessage(content="No homework.", id="a2"),
            AIMessage(
                content="", id="a3",
                tool_calls=[{"name": "course_assignments",
                             "args": {"course_query": "stats"}, "id": "g2"}],
            ),
            AIMessage(content="No quizzes either.", id="a4"),
        ]
    )
    agent = build_agent(deps, model=model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "chat-1"}}

    first = agent.invoke(
        {"messages": [("user", "homework in stats?")], "date_hints": "",
         "date_window": None, "clarify": None},
        config,
    )
    assert first["messages"][-1].content == "No homework."

    second = agent.invoke(
        {"messages": [("user", "any quizzes in it?")], "date_hints": "",
         "date_window": None, "clarify": None},
        config,
    )
    assert second["messages"][-1].content == "No quizzes either."
    assert any(m.type == "human" and "homework" in m.content for m in second["messages"])


def test_ambiguous_course_pauses_then_resumes_with_the_pick():
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    courses = [
        Course(id=10, name="AI Strategy", course_code="94-804", is_favorite=True),
        Course(id=20, name="Introduction to Artificial Intelligence", is_favorite=True),
    ]
    deps, _ = _deps(courses)
    model = ScriptedModel(
        responses=[
            AIMessage(
                content="",
                id="c1",
                tool_calls=[{"name": "course_assignments",
                             "args": {"course_query": "AI Strategy"}, "id": "r1"}],
            ),
            AIMessage(content="Here's your AI class work.", id="c2"),
        ]
    )
    agent = build_agent(deps, model=model, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    # The model narrowed "my AI class" to "AI Strategy"; the graph re-checks the
    # student's own words and clarifies anyway.
    paused = agent.invoke(
        {"messages": [("user", "do I have work in my AI class?")],
         "date_hints": "", "date_window": None, "clarify": None},
        config,
    )
    interrupt_value = paused["__interrupt__"][0].value
    assert {o["id"] for o in interrupt_value["options"]} == {10, 20}

    resumed = agent.invoke(Command(resume=20), config)

    # remembered for the session (not persisted)
    assert deps.session_courses == {"ai": 20}
    assert resumed["messages"][-1].content == "Here's your AI class work."
