"""Command-line interface for Canvas Copilot."""

from __future__ import annotations

import typer

from canvas_copilot import __version__

app = typer.Typer(
    name="canvas-copilot",
    help="A local-first AI assistant for Canvas LMS course logistics.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def ask(question: str) -> None:
    """Ask a natural-language question about your Canvas courses."""
    typer.echo(f"You asked: {question!r}")
    typer.echo(
        "Canvas Copilot is not wired up yet — this is the M0 scaffold. "
        "The Canvas client and agent loop come in later milestones."
    )


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
