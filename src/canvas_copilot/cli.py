"""Command-line interface for Canvas Copilot."""

from __future__ import annotations

import sqlite3

import typer

from canvas_copilot import __version__, auth
from canvas_copilot.canvas.client import CanvasClient, CanvasError
from canvas_copilot.canvas.models import Course
from canvas_copilot.config import get_settings
from canvas_copilot.resolve import Resolution, resolve_course
from canvas_copilot.storage import CourseCache, NicknameStore, connect

app = typer.Typer(
    name="canvas-copilot",
    help="A local-first AI assistant for Canvas LMS course logistics.",
    no_args_is_help=True,
    add_completion=False,
)

nickname_app = typer.Typer(help="Manage course nicknames.", no_args_is_help=True)
app.add_typer(nickname_app, name="nickname")


def _client() -> CanvasClient:
    settings = get_settings()
    return CanvasClient(settings.canvas_base_url, auth.get_token() or "")


def _fetch_courses() -> list[Course]:
    with _client() as client:
        return client.list_courses()


def _open_storage() -> tuple[sqlite3.Connection, CourseCache, NicknameStore]:
    conn = connect()
    return conn, CourseCache(conn), NicknameStore(conn)


def _label(course: Course) -> str:
    name = course.nickname or course.name or "(unnamed)"
    return f"{name} [{course.course_code or '?'}] — id {course.id}"


def _cached_courses(*, force: bool = False) -> list[Course]:
    _, cache, _ = _open_storage()
    return cache.get_courses(_fetch_courses, force=force)


@app.command()
def login() -> None:
    """Store your Canvas personal access token in the OS keychain."""
    token = typer.prompt("Canvas personal access token", hide_input=True).strip()
    if not token:
        typer.echo("No token entered; nothing stored.")
        raise typer.Exit(1)
    auth.store_token(token)
    typer.echo("Token stored in the keychain. Try: canvas-copilot whoami")


@app.command()
def logout() -> None:
    """Remove the stored Canvas token from the keychain."""
    typer.echo("Token removed." if auth.delete_token() else "No token was stored.")


@app.command()
def whoami() -> None:
    """Show which Canvas account the stored token belongs to."""
    try:
        with _client() as client:
            user = client.get_current_user()
    except CanvasError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1)
    typer.echo(f"{user.name} (id {user.id})")
    if user.primary_email:
        typer.echo(user.primary_email)


@app.command()
def courses(
    all_courses: bool = typer.Option(
        False, "--all", "-a", help="Include past (non-starred) courses."
    ),
) -> None:
    """List your starred Canvas courses (or all, with --all)."""
    try:
        course_list = _cached_courses()
    except CanvasError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1)
    if not course_list:
        typer.echo("No active courses found.")
        return

    shown = course_list if all_courses else [c for c in course_list if c.is_favorite]
    for course in shown:
        typer.echo(_label(course))

    hidden = len(course_list) - len(shown)
    if hidden > 0:
        typer.echo(f"\n+ {hidden} past course(s) — use `canvas-copilot courses --all`")


@app.command()
def refresh() -> None:
    """Re-fetch the course list from Canvas into the local cache."""
    try:
        course_list = _cached_courses(force=True)
    except CanvasError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1)
    typer.echo(f"Cached {len(course_list)} course(s).")


@app.command()
def resolve(
    query: str,
    all_courses: bool = typer.Option(
        False, "--all", "-a", help="Search past (non-starred) courses from the start."
    ),
) -> None:
    """Show how a course reference would be resolved (diagnostic)."""
    _, cache, nicknames = _open_storage()
    try:
        course_list = cache.get_courses(_fetch_courses)
    except CanvasError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1)

    result = resolve_course(query, course_list, nicknames, search_all=all_courses)
    _print_resolution(result, course_list)


def _print_resolution(result: Resolution, course_list: list[Course]) -> None:
    tag = " (past course)" if result.past_course else ""
    if result.status == "resolved" and result.course:
        typer.echo(f"Resolved: {_label(result.course)}{tag}  ({result.reason})")
    elif result.status == "confirm" and result.course:
        typer.echo(f'Did you mean "{_label(result.course)}"{tag}?  ({result.reason})')
    elif result.status == "ambiguous":
        typer.echo("Which course are you referring to?")
        for i, course in enumerate(result.candidates, start=1):
            typer.echo(f"  {i}. {_label(course)}")
    else:
        typer.echo(f'No course matches "{result.query}". Your starred courses:')
        for course in course_list:
            if course.is_favorite:
                typer.echo(f"  - {_label(course)}")
        typer.echo("(add --all to search past courses)")


@nickname_app.command("add")
def nickname_add(phrase: str, course_id: int) -> None:
    """Map a phrase to a course, e.g. `nickname add "ml" 12345`."""
    try:
        course_list = _cached_courses()
    except CanvasError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1)
    if course_id not in {c.id for c in course_list}:
        typer.echo(
            f"No cached course with id {course_id}. Run `canvas-copilot courses` first."
        )
        raise typer.Exit(1)
    _, _, nicknames = _open_storage()
    nicknames.add(phrase, course_id, source="manual")
    typer.echo(f'"{phrase}" -> course {course_id}')


@nickname_app.command("list")
def nickname_list() -> None:
    """List stored nicknames."""
    _, _, nicknames = _open_storage()
    entries = nicknames.list()
    if not entries:
        typer.echo("No nicknames stored.")
        return
    for entry in entries:
        typer.echo(
            f'{entry.display_phrase!r} -> course {entry.course_id}  ({entry.source})'
        )


@nickname_app.command("remove")
def nickname_remove(phrase: str) -> None:
    """Remove a stored nickname."""
    _, _, nicknames = _open_storage()
    typer.echo("Removed." if nicknames.remove(phrase) else "No matching nickname.")


@app.command()
def ask(
    question: str,
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show the agent's tool calls."
    ),
) -> None:
    """Ask a natural-language question about your Canvas courses."""
    import uuid
    from datetime import date

    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from canvas_copilot.agent import AgentDeps, build_agent
    from canvas_copilot.agent.dates import hints_for

    settings = get_settings()
    _, cache, nicknames = _open_storage()
    client = _client()
    deps = AgentDeps(client=client, cache=cache, nicknames=nicknames)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    def _show_tools(messages: list) -> None:
        if not verbose:
            return
        for message in messages:
            for call in getattr(message, "tool_calls", None) or []:
                typer.echo(f"  → {call['name']}({call['args']})", err=True)
            if isinstance(message, ToolMessage) and message.content:
                typer.echo(f"  ← {message.content.splitlines()[0]}", err=True)

    try:
        agent = build_agent(
            deps,
            model_name=settings.model,
            ollama_host=settings.ollama_host,
            checkpointer=InMemorySaver(),
        )
        state = agent.invoke(
            {
                "messages": [HumanMessage(content=question)],
                "date_hints": hints_for(question, date.today()),
                "clarify": None,
            },
            config,
        )
        _show_tools(state["messages"])

        while state.get("__interrupt__"):
            prompt_payload = state["__interrupt__"][0].value
            typer.echo(prompt_payload["prompt"])
            raw = typer.prompt("Pick a number").strip()
            options = prompt_payload["options"]
            try:
                picked = options[int(raw) - 1]["id"]
            except (ValueError, IndexError):
                typer.echo("No selection made.")
                picked = None
            state = agent.invoke(Command(resume=picked), config)
            _show_tools(state["messages"])
    except CanvasError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1)
    finally:
        client.close()

    if verbose:
        typer.echo("", err=True)
    final = next(
        (
            m.content
            for m in reversed(state["messages"])
            if isinstance(m, AIMessage) and m.content
        ),
        "(no answer)",
    )
    typer.echo(final)


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
