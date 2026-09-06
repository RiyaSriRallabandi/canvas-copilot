"""Command-line interface for Canvas Copilot."""

from __future__ import annotations

import typer

from canvas_copilot import __version__, auth
from canvas_copilot.canvas.client import CanvasClient, CanvasError
from canvas_copilot.config import get_settings

app = typer.Typer(
    name="canvas-copilot",
    help="A local-first AI assistant for Canvas LMS course logistics.",
    no_args_is_help=True,
    add_completion=False,
)


def _client() -> CanvasClient:
    settings = get_settings()
    return CanvasClient(settings.canvas_base_url, auth.get_token() or "")


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
def courses() -> None:
    """List your active Canvas courses."""
    try:
        with _client() as client:
            course_list = client.list_courses()
    except CanvasError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1)
    if not course_list:
        typer.echo("No active courses found.")
        return
    for course in course_list:
        label = course.nickname or course.name or "(unnamed)"
        typer.echo(f"{course.id:>8}  {course.course_code or '?':<18}  {label}")


@app.command()
def ask(question: str) -> None:
    """Ask a natural-language question about your Canvas courses."""
    typer.echo(f"You asked: {question!r}")
    typer.echo(
        "Canvas Copilot is not fully wired up yet. Structured lookups and the "
        "agent loop arrive in later milestones."
    )


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
