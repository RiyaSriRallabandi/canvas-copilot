"""The Canvas Copilot agent as an explicit LangGraph StateGraph.

    START -> agent -> (route)
                       |  tool calls, under the cap  -> tools -> agent
                       |  tool calls, at the cap     -> finalize -> END
                       |  no tool calls              -> END

``agent`` builds a fresh system message each turn (today's date, the current
course list, resolved date phrases) rather than storing it in state, so the
context never goes stale. ``tools`` catches bad/missing arguments and feeds the
error back so the model can retry.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from canvas_copilot.agent.tools import AgentDeps, build_tools
from canvas_copilot.prompts import system_prompt

MAX_TOOL_TURNS = 4


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    date_hints: str


def _make_model(model_name: str, ollama_host: str) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=model_name, temperature=0.0, num_predict=1024, base_url=ollama_host
    )


def _system_message(deps: AgentDeps, today: date, date_hints: str) -> SystemMessage:
    courses = deps.courses()
    current = [c for c in courses if c.is_favorite] or courses
    course_lines = "\n".join(
        f"  - id {c.id}: {c.nickname or c.name} [{c.course_code or '?'}]"
        for c in current
    )
    context = [
        f"\n\nToday is {today.strftime('%A, %B %d, %Y')} ({today.isoformat()}).",
        f"\nThe student's current courses:\n{course_lines}",
    ]
    if date_hints:
        context.append(f"\nDate phrases in the question: {date_hints}.")
    return SystemMessage(content=system_prompt() + "".join(context))


def _tool_turns(messages: list[AnyMessage]) -> int:
    return sum(
        1 for m in messages if isinstance(m, AIMessage) and m.tool_calls
    )


def build_agent(
    deps: AgentDeps,
    *,
    model: BaseChatModel | None = None,
    model_name: str = "qwen2.5:3b",
    ollama_host: str = "http://localhost:11434",
    today: date | None = None,
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
        for call in last.tool_calls:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                content = f"ERROR: no tool named {call['name']!r}."
            else:
                try:
                    content = str(tool.invoke(call["args"]))
                except Exception as exc:  # noqa: BLE001 - report so the model retries
                    content = f"ERROR: {exc}. Check the arguments and try again."
            results.append(ToolMessage(content=content, tool_call_id=call["id"]))
        return {"messages": results}

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

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools" if _tool_turns(state["messages"]) < MAX_TOOL_TURNS else "finalize"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", run_tools)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, ["tools", "finalize", END])
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile()
