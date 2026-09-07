# Architecture

## Two data flows

Canvas Copilot keeps two concerns separate:

1. **Canvas data** comes from the institution's Canvas REST API over HTTPS. This
   is unavoidable — the data lives there — and it is the only outbound network
   traffic.
2. **Language understanding** happens on the local machine. A small model
   (`qwen2.5:3b`) runs through Ollama. No question, grade, or assignment text is
   sent to a hosted AI provider.

## The agent is a graph, not a loop

The agent is a LangGraph state machine. Each node is a plain Python function;
only one node calls the model.

```
question
   │
   ▼
route_start ──── regex screen: is this "do my graded work"?
   │                 └─ yes ─→ refuse (canned message) ─→ done
   │ no
   ▼
agent ────────── the model call. Given the question, history, and tool
   │             schemas, it returns either a tool call or a final answer.
   ▼
route_agent ──── tool call? loop. no tool call? done. hit the 4-turn cap? finalize.
   │
   ▼
run_tools ────── Python, between model turns:
   │              • if the question names a course explicitly, resolve it from
   │                the student's words and override whatever the model passed
   │              • apply the date window the question implies (and clear any
   │                the model invented)
   │              • execute the tool (this is what calls Canvas)
   │              • if the course is ambiguous → clarify
   │
   ├─ clarify ── interrupt(): pause, show a numbered list, resume with the pick
   │
   └── loop back to agent with the tool results
   ▼
final answer
```

The model's job is narrow: pick a tool, and turn the tool's output into a
sentence. The parts a 3B model gets wrong — which course, which dates, whether
to refuse — are done in code it cannot skip. `docs/agent-reliability.md` covers
what those failure modes are and how each is contained.

## The tools

The model sees six tools:

| Tool | Returns |
|---|---|
| `list_courses` | the student's courses |
| `resolve_course(query)` | which course a name/nickname refers to |
| `course_assignments(course_query, due_after?, due_before?)` | one course's assignments, with points, submission status, and lock date |
| `course_content(course_query, question)` | passages from the course's syllabus / pages / announcements / assignment text that match the question, with links |
| `get_todo(due_after?, due_before?)` | the to-do list across all courses |
| `get_upcoming_events` | upcoming events and due dates across all courses |

`course_assignments` and `course_content` resolve the course themselves, so the
model never handles a course id — it passes the student's words and gets the
answer back. `course_content` runs the same vector search as the `search`
command; if the course has not been indexed yet, it indexes it first.

## Libraries

| Library | Role |
|---|---|
| `langchain-core` | message types (`HumanMessage`, `AIMessage`, `ToolMessage`), the `@tool` decorator, the JSON tool schema the model sees |
| `langchain-ollama` | the live connection to the local model — sends the conversation and tool schemas, parses the reply into a structured `AIMessage` |
| `langgraph` | the state machine: nodes, routing, the clarification pause, per-session memory |
| `httpx` | the Canvas HTTP client |
| `pydantic` | typed models for the Canvas fields the app uses |
| `rapidfuzz` | fuzzy course-name matching |

## Storage

A SQLite database (`~/Library/Application Support/canvas-copilot/`) caches the
course list (24-hour freshness), holds manually set course nicknames, and stores
the chunked text of each course's syllabus, pages, announcements, and assignment
descriptions (built by `canvas-copilot index`). It is a lookup accelerator, not
a record of Canvas data. Schema changes are applied by a small ordered list of
migrations tracked with `PRAGMA user_version`.

The Canvas token is kept in the OS keychain, never in a file.

## Session memory

`ask` is a single question. `chat` keeps one conversation: an in-memory
checkpointer holds the message history and the resolved-course context, so
"any quizzes in it?" reuses the course from the previous turn. That memory lives
for the length of the `chat` process and is not written to disk.
