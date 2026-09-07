# Choosing the model

The agent runs on **`qwen2.5:3b`**. This is how that choice was made and what the
alternatives showed.

## Constraints

The model ships with the app and runs on a student laptop, so download size and
latency matter. It also has to make reliable structured tool calls — the right
tool, the right arguments — which small models are weaker at. The candidates
were all 3B–8B instruction models with tool-calling support, run locally through
Ollama with `ChatOllama.bind_tools()`, the same interface the agent uses.

## Single-turn comparison — `qwen2.5:3b` vs `llama3.2:3b`

First pass: given a question and the tool schemas, is the model's first tool call
correct? 12 cases, 3 runs each.

| | qwen2.5:3b | llama3.2:3b |
|---|---|---|
| Tool accuracy | **1.0** | 0.70 |
| Refusal accuracy | **1.0** | 0.0 |
| Latency (p50) | 1.6 s | 1.9 s |
| Download | 1.9 GB | 2.0 GB |

The failure patterns mattered more than the totals. `llama3.2:3b` missed *every*
case where the student named a specific course — it never resolved the course
first, which is the flow the whole design centers on — and it did not hold the
refusal boundary against indirect phrasing. `qwen2.5:3b` missed one case
("what courses am I taking this semester"), which turned out to be a
tool-description wording issue and was fixed by sharpening the
`list_courses` / `resolve_course` descriptions.

## Multi-turn comparison — `qwen2.5:3b` vs `qwen2.5:7b`

The single-turn test does not predict conversational behavior, so a second eval
runs 17 multi-turn scenarios through the real agent against canned Canvas data,
scoring tool sequencing, answer structure, and refusals.

Before the reliability work in `docs/agent-reliability.md`:

| | qwen2.5:3b | qwen2.5:7b |
|---|---|---|
| Overall | 0.80 | 0.80 |
| Tool sequencing | 0.70 | 0.70 |
| Answer structure | 0.55 | 0.65 |
| Refusal | 1.0 | 1.0 |
| Latency / scenario | 7 s | 15 s |
| Download | 1.9 GB | 4.7 GB |

The 7B scored the same on tool sequencing — it fixed some scenarios and broke
others rather than being systematically better — for 2.5× the download and 2×
the latency. The ceiling was in how the agent steers the model, not in the
model's capacity.

## Outcome

With the deterministic scaffolding in place (a combined course tool, injected
date windows, a pre-model refusal screen, phrase-based course resolution),
`qwen2.5:3b` scores **1.0 across all 17 scenarios**. No model change was needed.

The eval lives in `evals/` and runs with `make eval`. It re-runs after any change
that could affect agent behavior.
