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

from datetime import date
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from canvas_copilot.agent.guardrails import REFUSAL, is_solve_request
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
    # (start, end) ISO dates resolved from the question; injected into
    # get_todo / course_assignments when the model omits the dates.
    date_window: tuple[str, str] | None
    clarify: Clarification | None


_DATE_TOOLS = {"get_todo", "course_assignments"}


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

    def route_start(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, HumanMessage) and is_solve_request(last.content):
            return "refuse"
        return "agent"

    def refuse(state: AgentState) -> dict:
        return {"messages": [AIMessage(content=REFUSAL)]}

    def agent(state: AgentState) -> dict:
        messages = [
            _system_message(deps, today, state.get("date_hints", "")),
            *state["messages"],
        ]
        return {"messages": [llm_with_tools.invoke(messages)]}

    def run_tools(state: AgentState) -> dict:
        last = state["messages"][-1]
        window = state.get("date_window")
        results: list[ToolMessage] = []
        clarify: Clarification | None = None
        for call in last.tool_calls:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                results.append(ToolMessage(
                    content=f"ERROR: no tool named {call['name']!r}.",
                    tool_call_id=call["id"],
                ))
                continue

            args = dict(call["args"])
            if call["name"] in _DATE_TOOLS and window and not args.get("due_after"):
                args["due_after"], args["due_before"] = window

            try:
                content = str(tool.invoke(args))
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
            results.append(ToolMessage(content=content, tool_call_id=call["id"]))
        return {"messages": results, "clarify": clarify}

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
            content=f'The student means "{chosen["label"]}". Call the same tool '
            f'again with course_query "{chosen["label"]}" to continue.',
            tool_call_id=pending["tool_call_id"],
        )
        return {"messages": [message], "clarify": None}

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
    graph.add_node("refuse", refuse)
    graph.add_node("tools", run_tools)
    graph.add_node("clarify", clarify_node)
    graph.add_node("finalize", finalize)
    graph.add_conditional_edges(START, route_start, ["agent", "refuse"])
    graph.add_edge("refuse", END)
    graph.add_conditional_edges("agent", route_agent, ["tools", "finalize", END])
    graph.add_conditional_edges("tools", route_tools, ["clarify", "agent"])
    graph.add_edge("clarify", "agent")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
