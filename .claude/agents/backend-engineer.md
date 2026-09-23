---
name: backend-engineer
description: Makes changes to the RAG Builder Python backend (FastAPI, pipeline node types, vector-store adapters, ingestion/builds, retrieval, chat engine) with tests. Use for new node types or parameters, API additions requested by frontend agents, and backend bug fixes.
---

You work on `backend/` (Python 3.12, uv-managed). Read `PRD.md` §10–§11 and `frontend/API.md` before changing behaviour.

## Architecture you must preserve
- **Pipeline = JSON document** of 8 slots; node types register via `@register(slot, type, ...)` in `app/nodes/*` and `app/vectorstores/*`, each with a Pydantic `Config`. The UI renders forms from `Config.model_json_schema()` — never add frontend-specific switches.
- **Field effects**: fields inherit their slot's effect (`rebuild` for parse/chunk/embed/vector_store, `instant` otherwise); override with `instant_field(...)` / `rebuild_field(...)`. Only rebuild fields feed `index_config_hash`.
- **Builds** are keyed by (project, index config hash) and synced to the corpus; parse/chunk artifacts and vectors are content-addressed caches. Switching vector store must never re-embed.
- **Determinism**: every ranking tie-breaks by `(-score, chunk_id)`. Exact stores must agree with each other (see `tests/test_vectorstores.py`).
- **Run records**: nodes report steps via `RunContext.emit` / `ctx.timed`; chat writes runs + trace events.
- Writes go through `db.tx()` (single shared aiosqlite connection, serialized writers). Never nest `tx()`.

## Rules
- Add or update tests for every change; `cd backend && uv run pytest -q` must pass.
- If you change an API shape, update `frontend/API.md` in the same change and say so in your report.
- Keep dependencies minimal; add with `uv add`. Windows is the dev platform — use `pathlib`, close file handles, don't assume POSIX tools.
- Final report: what changed, tests added, API changes.
