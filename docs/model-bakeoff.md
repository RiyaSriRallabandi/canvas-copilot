# Model bake-off (M3)

**Decision: build on `qwen2.5:3b`.**

## Method

Single-turn tool selection: for each case, send the query + the 6 M4 tool
schemas (as stubs) to the model and check its **first** tool call — name, and
key string args. 12 cases (10 tool-selection + 2 refusal probes), 3 runs each,
temperature 0, via `langchain-ollama` `ChatOllama.bind_tools()` — the same
interface the M4 LangGraph agent uses.

Run it: `uv run python -m canvas_copilot.evals`

## Results (2026-09-06)

| Metric | qwen2.5:3b | llama3.2:3b |
|---|---|---|
| Tool accuracy | **0.90** (9/10) | 0.50 (5/10) |
| Refusal accuracy | **1.0** (2/2) | 0.5 (1/2) |
| Latency p50 | 2.16 s | 2.27 s |
| Latency p95 | 9.15 s* | 4.95 s |
| Download size | 1.93 GB | 2.02 GB |

\* almost certainly first-call model load; re-measure with a warmup.

## Why qwen

The failure *patterns* decided it, not just the totals:

- **llama3.2:3b fails every `resolve_course` case** — when the student names a
  specific course ("work in Stats?", "midterm for Intro to AI?"), it does not
  resolve the course first. That is a structural failure in the flow the whole
  design centers on. It also fails the indirect-refusal probe ("walk me through
  the solution…").
- **qwen2.5:3b fails one case** — `list-courses` ("What courses am I taking this
  semester?"). Follow-up probing showed qwen calls `resolve_course` (with empty
  args) on phrasings like "…this semester" / "all my classes", but handles
  "what courses am I taking" / "list my courses" correctly. Sharpening the
  `list_courses` vs `resolve_course` descriptions fixes it. This is a
  tool-description clarity issue, addressed in M4.

## Follow-ups for M4

- Draw the `list_courses` vs `resolve_course` boundary clearly in tool
  descriptions (and re-run this eval to confirm no regressions).
- Add argument validation + retry to the agent loop: models sometimes emit a
  tool call with missing required args (`resolve_course({})`).
- Re-measure latency with a warmup call.

## Caveats

Small sample (12 cases × 3 runs), single-turn only. The effect size is large and
the failure patterns are systematic, but the golden-set eval in M7 is the real
measure.
