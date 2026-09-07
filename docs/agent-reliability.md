# Agent reliability notes (qwen2.5:3b)

Observed behaviours of the local model driving the agent, and what we do about
them. Feeds the guardrail + prompt work in M6 and the eval in M7.

## Observed

| Behaviour | Example |
|---|---|
| Pre-disambiguates a course itself | For "work in my AI class" it calls `resolve_course("AI Strategy")` — picking one of two AI courses — instead of passing the student's word "AI". |
| Parallel-calls `resolve_course` + `get_assignments` in one turn | Guesses a `course_id` from the prompt context before `resolve_course` returns. |
| Skips `resolve_course` entirely | Calls `get_assignments` with an id lifted straight from the course list in context. |
| Omits date arguments | "what's due this week" → `get_todo()` with no `due_after` / `due_before`, then presents overdue items as "this week". |
| Verbose answers | Trailing "Please submit these by their deadlines", lists every assignment when only upcoming was asked. |

## Mitigations in place (M4–M5)

- **`known_course_ids` guardrail** (`agent/graph.py`): `get_assignments` is
  rejected with an error unless its `course_id` came from a `resolve_course` or
  `list_courses` result earlier in the same run. Forces resolve-before-lookup;
  the model retries and self-corrects.
- **Deterministic dates**: relative phrases resolved to ISO ranges in
  `agent/dates.py` and injected into the prompt; the model only has to copy them.
- **Arg-error retry**: bad/missing tool args are returned as an error message so
  the model gets another turn.
- **Prompt**: explicit "pass the student's own words", "only use an id a tool
  gave you", "don't call resolve_course for all-course questions".

## M5.5

- **`chat` command**: interactive session, one `thread_id` + `InMemorySaver`, so
  message history and `known_course_ids` carry across questions — "any quizzes
  in it?" reuses the course resolved a turn earlier. Verified live. Still
  gated by the model reliably calling `resolve_course` in the first place.
- **Stale learned nicknames**: a `learned` nickname only resolves while its
  course is starred; `refresh` prunes learned nicknames whose course is no
  longer active. Manual nicknames are untouched.

## M5.5 prompt fixes

- Removed course **ids** from the system-prompt course list — qwen was using
  them to skip `resolve_course`. Without ids it must call a tool; when the
  `known_course_ids` guardrail rejects a guessed id, it now recovers by calling
  `resolve_course` instead of giving up.
- Removed the literal `[Assignment name](url)` formatting example — the model
  was emitting it verbatim when it had no real data.
- Added "answer course naming/counting from context, but MUST use a tool for
  assignments/dates" and "don't restate earlier answers".

## Model size — decided (M6): stay on qwen2.5:3b

The M6 multi-turn eval (17 scenarios, real agent) scored **qwen2.5:3b and
qwen2.5:7b identically on tool sequencing (0.70)**. The 7B is not systematically
better — it fixes some scenarios and breaks others — for 2.5× the download and
2× the latency. See `docs/model-bakeoff.md`. So the ~0.70 ceiling is a steering
problem, addressed by:

## What was done (M6) and the effect

Multi-turn eval score went **0.70 → 1.00 on tool sequencing** (2 runs, 17
scenarios) with no model change:

1. **`course_assignments("<course words>")`** — one tool that resolves the
   course internally, replacing the `resolve_course` → `get_assignments`
   two-step the model kept skipping. Raw `get_assignments` and the
   `known_course_ids` guardrail removed (no id to guess).
2. **Date-window injection** — the graph resolves the question's date phrase to
   an ISO range and injects it into `get_todo` / `course_assignments` when the
   model omits it. The model no longer has to remember.
3. **Pre-LLM solve-request screen** (`agent/guardrails.py`) — regex patterns for
   "do my homework", "walk me through the solution", "check my answer" route
   straight to a refusal before the agent runs. System prompt is the backstop.
4. **Prompt** cut ~50→~40 lines, rules first, one worked example.

## Course-reference handling (M6 follow-up)

The 3B narrows a vague reference before the tool sees it ("my AI class" →
`course_assignments("AI Strategy")`). Two fixes:

- **The student's own words are authoritative.** `run_tools` extracts an
  explicit course phrase from the last user message — text after "in/for/about"
  that isn't a pronoun. If present it is resolved and *overrides* the model's
  `course_query` (ambiguous → clarify; resolved → use the canonical name). If
  there's no explicit phrase but the message refers back ("does it...", "that
  class"), the last resolved course this session is used. Only if neither
  applies does the model's guess go through. Verified live.
- **Clarification picks are session-scoped**, not persisted. The pick goes into
  `AgentDeps.session_courses` (lives for one `ask`/`chat` process), so a
  follow-up in the same conversation reuses it, but a new session starts fresh.
  Only `nickname add` creates a permanent mapping. `NicknameStore.learn` /
  `prune_learned` are now unused by the agent (kept for the manual-nickname
  path and tests).

## Levers not pulled

- **Bigger model** — 7B scored identically (see `docs/model-bakeoff.md`).
- **Constrained generation** (Ollama JSON mode) — not needed at 1.00.
- **Fine-tuning** — needs a labeled dataset, can't train on an 8 GB Mac,
  brittle. Revisit only if scores regress in real use.

## Still open → M6 / M7

- Model still sometimes omits date args to `get_todo` — consider making the
  graph inject the resolved window when a date phrase is present and the tool
  was called without one.
- Answer verbosity / format — prompt tuning with real examples.
- M7 eval must check tool *arguments* and multi-turn sequences, not just the
  first tool name.
