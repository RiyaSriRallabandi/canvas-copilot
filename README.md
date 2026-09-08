# Canvas Copilot

A local-first assistant for [Canvas LMS](https://www.instructure.com/canvas). You
ask a course-logistics question in plain language and get a direct answer with a
link to the relevant Canvas page, instead of clicking through several pages
yourself.

*"What's due this week?"* · *"Do I have a midterm in Intro to AI?"* ·
*"How many points is the term paper, and did I submit it?"*

It is a navigation and convenience tool, not an academic one. It looks up and
summarizes logistics — assignments, due dates, points, submission status, exams.
It does not help complete graded work and refuses requests to do so.

## How it works

- **Read-only.** Every call to Canvas is a `GET`. The client raises rather than
  send anything else, so the app cannot submit, edit, or delete.
- **On-device language model.** The agent runs on a small local model
  (`qwen2.5:3b`) through [Ollama](https://ollama.com). Questions, grades, and
  assignment text never leave the machine for a third-party AI service — the only
  outbound calls are to your own institution's Canvas API.
- **Deterministic where it matters.** A LangGraph state machine surrounds the
  model. Course resolution, date ranges, and the refuse-graded-work boundary are
  handled by ordinary Python, not left to the model. The model chooses which
  tool to call and phrases the final answer; the code does the fragile parts.
- **Asks instead of guessing.** When a course reference is ambiguous ("my AI
  class" with two AI courses), the agent pauses and offers a numbered list to
  pick from.

`docs/architecture.md` describes the pieces in more detail.

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) running locally, with `qwen2.5:3b` pulled
- A Canvas personal access token (Account → Settings → New Access Token)

## Setup

```bash
uv sync
ollama pull qwen2.5:3b

# Canvas connection: base URL in .env, token in the OS keychain
cp .env.example .env          # then set CANVAS_BASE_URL, e.g. https://canvas.cmu.edu/api/v1
uv run canvas-copilot login   # paste the token (stored in the keychain, never a file)
uv run canvas-copilot whoami  # confirms the token works
```

## Use

```bash
uv run canvas-copilot serve           # web chat UI in the browser
uv run canvas-copilot ask "what assignments do I have due this week?"
uv run canvas-copilot chat            # interactive terminal session, remembers context
uv run canvas-copilot courses         # your starred courses
uv run canvas-copilot index --all     # read course content for the questions below
uv run canvas-copilot nickname add "ml" 12345
```

Add `--verbose` to `ask` / `chat` to see the tool calls.

## Development

```bash
make check         # ruff, pyright, pytest — what CI runs
make check-local   # the above plus live tests (needs Ollama + a token)
make eval          # the multi-turn scenario eval against a model
```

CI runs on every push and pull request (`.github/workflows/ci.yml`).

## Scope

Two kinds of question are answered:

- **Structured** — assignments, due dates, points, submission status, the to-do
  list, upcoming events — straight from Canvas's REST API.
- **Prose** — the grading breakdown, late policy, class time and room, office
  hours, exam format, whether LockDown Browser is required — by indexing each
  course's syllabus, pages, and announcements (`canvas-copilot index`) and
  searching them with a keyword + embedding hybrid. A syllabus that lives in an
  off-Canvas document (a Google Doc) is answered with the link, not a guess.

`docs/decisions.md` records the design choices and why; `docs/phase-2-backlog.md`
lists what is not covered yet.

## License

[MIT](LICENSE) © 2026 Riya Sri Rallabandi
