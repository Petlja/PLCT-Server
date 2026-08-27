# Agent Guide

The operational entry point for coding agents. Keep it short; canonical detail belongs in
`doc/`.

## Read first

1. [README.md](README.md) — what the server is and how it is installed.
2. [doc/ai_flow.md](doc/ai_flow.md) — the runtime and the whole query path. Read this before
   touching anything under `plct_server/ai/`.
3. [doc/config.md](doc/config.md) — configuration keys and where they are validated.
4. [doc/plct_ai_ctx_relations.md](doc/plct_ai_ctx_relations.md) and
   [doc/ai_knowledge_tools_relations.md](doc/ai_knowledge_tools_relations.md) — what the two
   upstream repositories hand this one. Their artifacts are inputs; do not edit them here.
5. The test file for the module you are about to change.

## Essential commands

```bash
uv sync
uv run python -m unittest tests.test_ai_tools tests.test_ai_encoding tests.test_auth \
                          tests.test_knowledge tests.test_ui_api
uv run python -m unittest tests.test_ai_tools        # one module, while iterating
dev-server.cmd                                       # local server on 127.0.0.1:9000
cd front-app && npm test -- --run                    # SPA tests (vitest)
cd front-app && npx tsc --noEmit                     # SPA typecheck
```

`tests/` has no `__init__.py`, so `unittest discover` cannot load it — name the modules.
Tests are offline: no API key, no network, no live model calls. Keep them that way.

## Ownership

- `plct_server/ai/engine.py` — the prompt, the model call, the tool list, and the two
  budget reports that bracket a run.
- `plct_server/ai/prompt_templates.py` — every string the model is sent. Changing one is a
  behavior change; say so.
- `plct_server/ai/tools/loop.py` — the tool loop: rounds, call reassembly, progress hooks.
- `plct_server/ai/tools/course_tools.py`, `knowledge_tools.py` — the search tools, their
  descriptions (prompt engineering, authored here) and their cutoffs.
- `plct_server/ai/tools/commands.py` — what a teacher can require of an answer by writing
  `/teaching` in the question, and the table that binds a command to a tool.
- `plct_server/ai/tools/evidence.py` — the per-request ledger: dedupe once, budget once.
- `plct_server/ai/narration.py` — how the pipeline words itself in the log.
- `plct_server/ai/debug_stream.py` — tees the pipeline log into the answer stream.
- `plct_server/endpoints/ui_api.py` — the `/api/chat` NDJSON wire format and the Serbian
  user-facing strings.
- `plct_server/knowledge/` — mirroring, indexing, chunk order, course lookups.
- `front-app/src/` — the React SPA that consumes the stream.

## Invariants

- The system message is assembled from named parts so it can be measured part by part.
  Changing how they are joined changes the prompt: verify the assembled string is
  unchanged when you only meant to change the reporting.
- Progress stages are a closed set. The engine owns `PROGRESS_STAGES`; the endpoint owns
  the wording. A stage with no message raises rather than streaming a blank line.
- Refused hits stay observable: counts and ranges at INFO, per-hit distances at DEBUG. A
  cutoff whose rejections are invisible cannot be recalibrated.
- Recoverable limits (budget spent, nothing near enough, already-provided passages) go back
  to the model as tool data, never as an exception.
- The model is implementation-blind: it asks natural-language questions and never sees
  chunk ids, ordinals, or retrieval mechanics.
- Library modules take a logger and never configure handlers or levels. Only
  `plct_server/__init__.py` and `debug_stream.install()` do that.
- With `debug_mode` on, the pipeline log is rendered in the browser beside the answer, so
  it is a product surface. Write log lines for someone watching one question be answered.

## Style

Match the surrounding code. It is documented, but the bar is high: a comment or docstring
earns its place by explaining a decision the code cannot show — why a cutoff is where it
is, why two things are separate, what breaks if the order changes. Do not narrate what the
next line already says, do not restate the signature, and do not write three paragraphs
where one sentence carries the reason. One-line docstrings are the default; a self-evident
helper needs none. Prefer trimming an existing comment to adding a second one beside it.

## Editing and validation

Make the smallest change in the owning module, run that module's tests, then widen. Add
tests for behavior changes — wire formats, prompt contracts, cutoffs, budget accounting,
and anything the SPA parses. Finish with the full command above plus the SPA tests if you
touched `front-app/`.

Update `doc/ai_flow.md` when the query path, the wire format, or a tuned constant changes.
Do not edit anything under `plct_server/eval/results/` by hand; it is generated output.
