# Canvas Copilot

A local-first AI assistant for [Canvas LMS](https://www.instructure.com/canvas) that answers
course-logistics questions in plain language — *"What assignments are due today?"*, *"Do I have
a midterm for Intro to AI?"* — and links you straight to the relevant Canvas page.

It is a **navigation and convenience tool, not an academic tool.** It finds and summarizes
information (assignments, due dates, exams, announcements). It will not help complete graded
work, and refuses requests to do so.

## Principles

- **Read-only.** Only `GET` requests to Canvas — it cannot submit, edit, or delete anything.
- **No solving assignments.** Explicit, adversarially tested refusal boundary.
- **Local-first AI.** Language-model inference runs on-device via [Ollama](https://ollama.com).
  No queries, grades, or assignment text are sent to a third-party AI provider — the only
  external calls are to your own institution's Canvas API.
- **Human-in-the-loop.** Anything that would leave the app (e.g. a drafted email) is shown to
  you for review — never sent automatically.

## Status

Early development. **Phase 1** (this milestone set) is a terminal CLI that answers
structured-data questions (assignments, due dates, calendar events) against a personal Canvas
access token. RAG over syllabi, reminders, email drafting, and a desktop app come later.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) (added in a later milestone)
- A Canvas personal access token (added in a later milestone)

## Setup

```bash
uv sync
uv run canvas-copilot --help
```

## License

[MIT](LICENSE) © 2026 Riya Sri Rallabandi
