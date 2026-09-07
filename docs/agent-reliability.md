# Agent reliability

The agent runs on `qwen2.5:3b` — small enough to bundle and run on a laptop, but
a weaker instruction-follower than a hosted frontier model. This is a record of
where it falls short and how the surrounding code compensates, so the model
stays a swappable component rather than the thing correctness depends on.

## Failure modes observed

| The model tends to… | Example |
|---|---|
| narrow a vague course reference itself | "work in my AI class" → `course_assignments("AI Strategy")`, picking one of two AI courses instead of passing "my AI class" through |
| skip the resolution step | calls a course tool with a course name it half-guessed |
| omit date arguments, or invent them | "what's due this week" → `get_todo()` with no window; "how many points is X" → a spurious "due today" filter that hides the assignment |
| leak on rephrased "solve it" requests | refuses "do my homework" but not "walk me through the solution" |
| lose the thread over a long chat | repeats an earlier answer, drifts off the current course |
| pad answers | trailing "please submit these by their deadlines"; lists everything when asked for one thing |

## What contains each

**Course reference.** `run_tools` does not trust the `course_query` the model
passes. It pulls the course phrase out of the student's own message (the text
after "in" / "for", ignoring pronouns), resolves that, and overrides the model's
argument with the result. An ambiguous phrase triggers the clarification pause
regardless of what the model narrowed it to. A follow-up that refers back
("does it…", "that class") uses the last course resolved in the session.

**List questions.** "which of my courses are about AI", "how many classes am I
taking" are answered from the course list already in context. If the model calls
a course tool for one of these, `run_tools` returns a note telling it to answer
directly — so "about AI" is never mistaken for a course named "AI".

**One combined tool.** `course_assignments` takes a course name and resolves it
internally. There is no separate "get assignments by id" tool, so there is no id
for the model to invent and no resolution step for it to skip.

**Dates.** `agent/dates.py` turns "today" / "this week" / "next week" into a
concrete date range using plain arithmetic. The graph owns the date window
entirely for `get_todo` and `course_assignments`: if the question implies a
range it is applied, and if the question says nothing about dates, any range the
model added is dropped.

**The refusal boundary.** Three layers:

- A regex screen (`agent/guardrails.py`) runs before the model. It matches the
  common direct and indirect forms — "do/solve/write/develop my <work>", "<work>
  for me", "help me <do> …", "walk me through the assignment", "check my answer",
  "step by step" near an assignment — and routes straight to a canned refusal.
  Verb inflections are covered (solve/solving/solved).
- Once a request is caught, the thread is marked `blocked`. Vague follow-ups
  ("keep going", "help me with the next part") stay refused, so the model can't
  be worn down over several turns. A clear logistics question ("when is it due",
  "how many points") lifts through.
- The system prompt tells the model to refuse as well, for phrasings the regex
  misses.

`tests/test_guardrails.py` holds ~30 phrasings the screen must catch (including
ones observed leaking in live testing) and ~18 legitimate questions it must not
block.

**Session memory.** `chat` keeps one thread through an in-memory checkpointer, so
the course context and history carry across turns. It lives for the length of
the process and is not persisted.

**Retry on bad arguments.** A tool call with unknown or missing arguments comes
back as an error message rather than a crash, giving the model another turn to
correct itself.

## Model choice

A 17-scenario multi-turn eval (`evals/`) scored `qwen2.5:3b` and `qwen2.5:7b`
identically on tool sequencing — 0.70 before the containment work above, with
the 7B fixing some scenarios and breaking others for 2.5× the download and 2×
the latency. The gap was in steering, not model capacity. With the containment
in place, `qwen2.5:3b` scores 1.0 across the eval. Details in
`docs/model-bakeoff.md`.

Levers deliberately left unused: a larger model (no measured benefit),
constrained JSON generation (not needed at 1.0), and fine-tuning (needs a
labeled dataset, cannot train on the target hardware, and is brittle to
maintain).

## Known residual limitation

The 3B still sometimes substitutes a specific course title for a vague reference
before `run_tools` sees it. When it does, the phrase-extraction override catches
the ambiguity from the student's original wording. If both the model and the
override miss it, the result is an answer about a plausible course, and the
student corrects it in one turn. The clarification mechanism itself is covered by
unit tests.
