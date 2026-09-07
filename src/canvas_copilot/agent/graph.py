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

import re
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

from canvas_copilot.agent._util import message_text
from canvas_copilot.agent.guardrails import REFUSAL, is_solve_request
from canvas_copilot.agent.tools import (
    AgentDeps,
    NeedsClarification,
    build_tools,
    course_label,
)
from canvas_copilot.prompts import system_prompt
from canvas_copilot.resolve import normalize as _normalize

MAX_TOOL_TURNS = 4

# {tool_call_id, query, options: [{id, label, name}]}
Clarification = dict[str, Any]


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    date_hints: str
    # (start, end) ISO dates resolved from the question; injected into
    # get_todo / course_assignments when the model omits the dates.
    date_window: tuple[str, str] | None
    clarify: Clarification | None


_DATE_TOOLS = {"get_todo", "course_assignments"}
_COURSE_TOOLS = {"course_assignments", "resolve_course"}

_PRONOUNS = {"it", "that", "this", "them", "those", "the same", "that one", "this one"}

# The chunk of a question that names a course: text after "in/for/about".
_COURSE_PHRASE = re.compile(
    r"\b(?:in|for|about)\s+(.+?)"
    r"(?:\s+(?:this|next|coming|due|by|on|today|tomorrow)\b.*)?[?.!]*$",
    re.IGNORECASE,
)
# A follow-up referring back to a course already discussed.
_PRONOUN_REF = re.compile(
    r"\b(it|that class|that course|the same( one)?|this class)\b", re.I
)


def _course_phrase(text: str) -> str | None:
    """An explicit course reference in the question, or None.

    None when there is no "in/for/about X", or X is just a pronoun.
    """
    match = _COURSE_PHRASE.search(text)
    if not match or not match.group(1).strip():
        return None
    phrase = match.group(1).strip()
    return None if _normalize(phrase) in _PRONOUNS else phrase


def _refers_back(text: str) -> bool:
    return _course_phrase(text) is None and bool(_PRONOUN_REF.search(text))


def _last_human_text(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message_text(message)
    return ""


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
        if isinstance(last, HumanMessage) and is_solve_request(message_text(last)):
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
        assert isinstance(last, AIMessage)  # route_agent only sends us here then
        window = state.get("date_window")
        student_text = _last_human_text(state["messages"])
        phrase = _course_phrase(student_text)
        results: list[ToolMessage] = []
        clarify: Clarification | None = None
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

            args = dict(call["args"])

            # The student's own words are authoritative for which course. The
            # model tends to narrow ("my AI class" -> "AI Strategy") or guess.
            if call["name"] in _COURSE_TOOLS:
                arg_key = (
                    "course_query" if call["name"] == "course_assignments" else "query"
                )
                if phrase is not None:
                    check = deps.resolve(phrase)
                    if check.status == "ambiguous":
                        clarify = {
                            "tool_call_id": call["id"],
                            "query": phrase,
                            "options": [
                                {
                                    "id": c.id,
                                    "label": course_label(c),
                                    "name": c.nickname or c.name,
                                }
                                for c in check.candidates
                            ],
                        }
                        continue
                    if check.status == "resolved" and check.course:
                        args[arg_key] = check.course.name
                elif _refers_back(student_text) and deps.last_course_id:
                    prev = next(
                        (c for c in deps.courses() if c.id == deps.last_course_id),
                        None,
                    )
                    if prev:
                        args[arg_key] = prev.name

            # The question's date intent is authoritative: use the resolved
            # window if there is one, otherwise drop any window the model
            # invented ("how many points is X" is not a dated question).
            if call["name"] in _DATE_TOOLS:
                if window:
                    args["due_after"], args["due_before"] = window
                else:
                    args.pop("due_after", None)
                    args.pop("due_before", None)

            try:
                content = str(tool.invoke(args))
            except NeedsClarification as need:
                clarify = {
                    "tool_call_id": call["id"],
                    "query": need.query,
                    "options": [
                        {
                            "id": c.id,
                            "label": course_label(c),
                            "name": c.nickname or c.name,
                        }
                        for c in need.candidates
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
            f"  {i}. {opt['label']}" for i, opt in enumerate(pending["options"], start=1)
        )
        picked_id = interrupt(
            {
                "type": "course_choice",
                "query": pending["query"],
                "prompt": f"Which course did you mean?\n{option_lines}",
                "options": pending["options"],
            }
        )
        chosen = next((o for o in pending["options"] if o["id"] == picked_id), None)
        if chosen is None:
            message = ToolMessage(
                content=f"NOT_FOUND: the student did not pick a course for "
                f'"{pending["query"]}".',
                tool_call_id=pending["tool_call_id"],
            )
            return {"messages": [message], "clarify": None}

        # Remember the pick for the rest of THIS session only (not persisted).
        deps.session_courses[_normalize(pending["query"])] = chosen["id"]
        name = chosen.get("name", chosen["label"])
        message = ToolMessage(
            content=f'The student means "{name}". Call the same tool again with '
            f'course_query "{name}" to continue.',
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
                "tools" if _tool_turns(state["messages"]) < MAX_TOOL_TURNS else "finalize"
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
