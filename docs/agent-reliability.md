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

## Still open → M6 / M7

- Model still sometimes omits date args to `get_todo` — consider making the
  graph inject the resolved window when a date phrase is present and the tool
  was called without one.
- Answer verbosity / format — prompt tuning with real examples.
- M7 eval must check tool *arguments* and multi-turn sequences, not just the
  first tool name.
