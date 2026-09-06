r"""The Canvas Copilot agent as an explicit LangGraph StateGraph.

    START -> agent -> (route_agent)
                       |  tool calls, under the cap  -> tools -> (route_tools)
                       |  tool calls, at the cap     -> finalize -> END
                       |  no tool calls              -> END

    tools -> (route_tools) --- ambiguous course --> clarify -> agent
                           \--- otherwise -----------------> agent

``agent`` builds a fresh system message each turn (today's date, the current
course list, resolved date phrases) rather than storing it in state, so the
context never goes stale. ``tools`` catches bad/missing arguments and feeds the
error back so the model can retry. When ``resolve_course`` reports an ambiguous
reference, ``tools`` defers its result and ``clarify`` pauses the graph
(``interrupt``) to ask the student which course they meant.
"""

from __future__ import annotations

import operator
import re
from datetime import date
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from canvas_copilot.agent.tools import (
    AgentDeps,
    NeedsClarification,
    build_tools,
    course_label,
)
from canvas_copilot.prompts import system_prompt

MAX_TOOL_TURNS = 4


class Clarification(TypedDict):
    tool_call_id: str
    query: str
    options: list[dict[str, Any]]  # [{"id": int, "label": str}]


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    date_hints: str
    clarify: Clarification | None
    # Course ids the agent has actually been handed by resolve_course /
    # list_courses this run. get_assignments is only allowed to use these —
    # it stops the model guessing an id straight from the prompt context.
    known_course_ids: Annotated[list[int], operator.add]


_RESOLVED_ID = re.compile(r"RESOLVED: id (\d+)")


def _make_model(model_name: str, ollama_host: str) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=model_name, temperature=0.0, num_predict=1024, base_url=ollama_host
    )


def _system_message(deps: AgentDeps, today: date, date_hints: str) -> SystemMessage:
    courses = deps.courses()
    current = [c for c in courses if c.is_favorite] or courses
    # Names only, no ids — the model must call resolve_course / list_courses to
    # get an id, rather than guessing one straight from this list.
    course_lines = "\n".join(
        f"  - {c.nickname or c.name} [{c.course_code or '?'}]" for c in current
    )
    context = [
        f"\n\nToday is {today.strftime('%A, %B %d, %Y')} ({today.isoformat()}).",
        f"\nThe student's current courses:\n{course_lines}",
    ]
    if date_hints:
        context.append(f"\nDate phrases in the question: {date_hints}.")
    return SystemMessage(content=system_prompt() + "".join(context))


def _tool_turns(messages: list[AnyMessage]) -> int:
    return sum(1 for m in messages if isinstance(m, AIMessage) and m.tool_calls)


def build_agent(
    deps: AgentDeps,
    *,
    model: BaseChatModel | None = None,
    model_name: str = "qwen2.5:3b",
    ollama_host: str = "http://localhost:11434",
    today: date | None = None,
    checkpointer: Any | None = None,
):
    today = today or date.today()
    llm = model or _make_model(model_name, ollama_host)
    tools = build_tools(deps)
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    def agent(state: AgentState) -> dict:
        messages = [
            _system_message(deps, today, state.get("date_hints", "")),
            *state["messages"],
        ]
        return {"messages": [llm_with_tools.invoke(messages)]}

    def run_tools(state: AgentState) -> dict:
        last = state["messages"][-1]
        results: list[ToolMessage] = []
        clarify: Clarification | None = None
        known = set(state.get("known_course_ids", []))
        learned: list[int] = []
        for call in last.tool_calls:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                results.append(
                    ToolMessage(
                        content=f"ERROR: no tool named {call['name']!r}.",
                        tool_call_id=call["id"],
                    )
                )
                continue
            if call["name"] == "get_assignments":
                course_id = call["args"].get("course_id")
                if course_id not in known and course_id not in learned:
                    results.append(
                        ToolMessage(
                            content=f"ERROR: course_id {course_id} did not come from "
                            "resolve_course or list_courses. Call resolve_course with "
                            "the student's own words first, then use the id it returns.",
                            tool_call_id=call["id"],
                        )
                    )
                    continue
            try:
                content = str(tool.invoke(call["args"]))
            except NeedsClarification as need:
                clarify = {
                    "tool_call_id": call["id"],
                    "query": need.query,
                    "options": [
                        {"id": c.id, "label": course_label(c)} for c in need.candidates
                    ],
                }
                continue  # its ToolMessage is emitted by the clarify node
            except Exception as exc:  # noqa: BLE001 - report so the model retries
                content = f"ERROR: {exc}. Check the arguments and try again."

            if call["name"] == "resolve_course":
                match = _RESOLVED_ID.search(content)
                if match:
                    learned.append(int(match.group(1)))
            elif call["name"] == "list_courses":
                learned.extend(c.id for c in deps.courses())
            results.append(ToolMessage(content=content, tool_call_id=call["id"]))
        return {"messages": results, "clarify": clarify, "known_course_ids": learned}

    def clarify_node(state: AgentState) -> dict:
        pending = state["clarify"]
        assert pending is not None
        option_lines = "\n".join(
            f"  {i}. {opt['label']}"
            for i, opt in enumerate(pending["options"], start=1)
        )
        picked_id = interrupt(
            {
                "type": "course_choice",
                "query": pending["query"],
                "prompt": f"Which course did you mean?\n{option_lines}",
                "options": pending["options"],
            }
        )
        chosen = next(
            (o for o in pending["options"] if o["id"] == picked_id), None
        )
        if chosen is None:
            message = ToolMessage(
                content=f'NOT_FOUND: the student did not pick a course for '
                f'"{pending["query"]}".',
                tool_call_id=pending["tool_call_id"],
            )
            return {"messages": [message], "clarify": None}

        deps.nicknames.learn(pending["query"], chosen["id"])
        message = ToolMessage(
            content=f"RESOLVED: id {chosen['id']} — {chosen['label']} "
            "(the student picked this from the list)",
            tool_call_id=pending["tool_call_id"],
        )
        return {
            "messages": [message],
            "clarify": None,
            "known_course_ids": [chosen["id"]],
        }

    def finalize(state: AgentState) -> dict:
        nudge = SystemMessage(
            content="Answer now using the information already gathered. "
            "Do not call any more tools."
        )
        messages = [
            _system_message(deps, today, state.get("date_hints", "")),
            *state["messages"],
            nudge,
        ]
        return {"messages": [llm.invoke(messages)]}

    def route_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return (
                "tools"
                if _tool_turns(state["messages"]) < MAX_TOOL_TURNS
                else "finalize"
            )
        return END

    def route_tools(state: AgentState) -> str:
        return "clarify" if state.get("clarify") else "agent"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", run_tools)
    graph.add_node("clarify", clarify_node)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_agent, ["tools", "finalize", END])
    graph.add_conditional_edges("tools", route_tools, ["clarify", "agent"])
    graph.add_edge("clarify", "agent")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
