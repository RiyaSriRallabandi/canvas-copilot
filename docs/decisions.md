# Design decisions

A running log of the choices that shaped the code, and why. Newest first within
each phase. Topic detail lives in the other files in this directory; this is the
short version with the reasoning.

## Phase 2 — content search

### Hybrid retrieval (keyword + vector), keyword-led

`course_content` ranks chunks with a BM25 keyword search (SQLite FTS5) and a
vector search (nomic-embed-text, cosine), then fuses the two lists with
reciprocal-rank fusion weighted toward the keyword side.

Pure vector search failed in practice: with a 768-dimension local embedder every
chunk in a course landed in a narrow cosine band (~0.35–0.40), so the exact
answer to "what's the grading breakdown" — a chunk literally headed "Grade
Breakdown" — did not rank in the top results. For policy and prose questions the
answer almost always contains the question's distinctive words, which BM25 ranks
decisively. Vector search stays for paraphrased questions. FTS5 is in the Python
standard library's SQLite, so it adds no dependency and no cost.

### Assignment descriptions demoted, not dropped

The vector search covers only *guidance* text — syllabus, pages, announcements,
module outlines. Assignment descriptions are still keyword-reachable (so "is
LockDown Browser required" finds the assignment that says so) but are kept out
of the semantic pass, where their volume and grading-flavoured language buried
the syllabus on policy questions. Assignment content is already served directly
by `course_assignments`.

### An off-Canvas syllabus is answered with the link

Some courses put nothing in the Canvas syllabus field but a sentence linking to
a Google Doc. That case is detected at index time (short body, external link)
and the URL is stored. `course_content` returns the link instead of assembling
a guess from whatever else was indexed. The external document is never fetched —
the product navigates Canvas, it does not read sources outside it.

### Content-schema version drives re-indexing

Each course's stored index records the schema version it was built under. When
chunking or retrieval changes, the constant is bumped and stale indexes rebuild
themselves on next use. This came out of shipping a retrieval change that left
old, incompatible chunks in place with no signal that they were stale.

### Small chunks, asymmetric embedding prefixes, cosine distance

Chunks are ~800 characters (down from ~1600) so a passage stays on one topic.
nomic-embed-text is trained with task prefixes, so indexed text gets
`search_document:` and queries get `search_query:`; without them retrieval was
noticeably worse. The vector table uses cosine distance — L2 discriminated
poorly on these embeddings.

### Index before use, not during the first question

Indexing a course is slow (fetch + chunk + embed). Doing it ahead of time — the
`index` command, and in future the GUI's "Gathering information…" step — keeps
the first question fast. The agent will index a course on demand if it has to,
but that is the fallback.

### RAG stack

`html2text` for HTML→text (keeps headings, drops markup), `pypdf` for PDF text,
`langchain-text-splitters` for structure-aware chunking, `nomic-embed-text` via
Ollama for embeddings, `sqlite-vec` for vector storage. All local, all free,
no service to sign up for.

## Phase 2 — agent

### The tool-call cap is per question, not per conversation

The agent stops calling tools after 4 tool turns and answers with what it has.
That count resets at each new question — otherwise a `chat` session stops
calling tools a few questions in and starts answering from stale context.

### "Which of my courses are about X" is answered without a tool

These questions are answered from the course list already in the prompt. The
graph intercepts any tool call on such a question and hands the model the
roster inline. For the recurring "about AI" case it also names the matching
courses outright, because the 3B otherwise counts "Data Science" as AI.

## Phase 1 — foundations

### LangGraph, with the model on a short leash

The agent is an explicit LangGraph state machine; only one node calls the model.
Course resolution, date-window handling, and the graded-work refusal run in
Python around the model, not in it — those are the parts a 3B gets wrong, and
they must not depend on model behaviour. LangGraph over a hand-rolled loop for
the checkpointing and the room to add branches; it is also a deliberately
portfolio-relevant choice.

### `qwen2.5:3b`

Chosen on measured tool-call accuracy, latency, and download size against
`llama3.2:3b` and a 7B. See `model-bakeoff.md`.

### Raw `httpx` Canvas client, GET-only

A thin wrapper rather than `canvasapi`, so the read-only guarantee is a single
`assert` in one place, request fixtures are easy to record for tests, and the
traffic is visible. Endpoint coverage is small enough that the library's
abstraction wasn't worth it.

### SQLite, migrations tracked with `PRAGMA user_version`

One local file, standard library, no server. Schema changes are an ordered list
of migrations; the pragma records how many have run. The Canvas token is kept
in the OS keychain, never in a file.

## Phase 2.5 — GUI

### A local web GUI before any packaged app

A `serve` command (FastAPI + one static page, opened in the browser) gives a
usable chat interface on top of the existing agent without the weeks of work a
distributable desktop app needs (bundling Ollama, installers, a first-run
wizard). That packaging is a separate, later effort.
