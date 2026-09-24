# RAGLabs

Build your own "chat with your documents" assistant from a web UI — no code.
Upload documents, choose and tune every part of the pipeline (including the vector database),
build the index, and chat with answers that cite their sources. An inspector shows which
passages were found, by which search path, and what each step cost.

**Phase 1 — Build & Chat.** See [`PRD.md`](PRD.md) for the full plan and [`IDEAS.md`](IDEAS.md)
for the idea catalogue.

## What you can tune

| Stage | Options |
|---|---|
| Parse | PyMuPDF4LLM (Markdown + tables), PyMuPDF (plain text, optional OCR), pypdf |
| Chunk | fixed, recursive, sentence packing, structure-aware (headings) — size, overlap, unit… Tables are never split. |
| Embed | local fastembed models (bge-small/base, MiniLM, arctic, nomic, mxbai) or Gemini / NVIDIA APIs |
| Vector store | NumPy (exact), FAISS (Flat / IVF / HNSW), Chroma, Qdrant (local mode), LanceDB (none / IVF / PQ / HNSW) |
| Retrieve | dense, keyword (BM25), hybrid, fused (+ exact error-message/code-symbol matching); RRF or weighted fusion, MMR, thresholds |
| Rerank | off, or local cross-encoders |
| Prompt | cited answer, concise, detailed, or your own template; context budget |
| Generate | Google Gemini or NVIDIA (free tiers); model, temperature, top-p, max tokens |

Every parameter is labelled **⚡ instant** (applies at query time) or **🔁 rebuild** (needs
re-indexing). Rebuilds reuse cached work: switching vector store never re-embeds.
Every saved configuration is an immutable version you can diff and switch back to at any time.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python is fetched automatically — the backend uses 3.12)
- Node.js 20+
- A free LLM key for chatting (retrieval and the inspector work without one):
  [Gemini](https://aistudio.google.com/apikey) or [NVIDIA](https://build.nvidia.com)

## Run it

```bash
cp .env.example .env          # then paste GEMINI_API_KEY and/or NVIDIA_API_KEY

# terminal 1 — backend (http://127.0.0.1:8000)
cd backend
uv sync
uv run uvicorn app.main:app

# terminal 2 — frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

Seed the demo project (the Pydantic v2 docs, ~500 chunks; the first run downloads a ~70 MB
embedding model):

```bash
cd backend
uv run python scripts/seed_demo.py
```

Then open the Playground and try:

- *How do I make a field optional with a default?*
- paste a raw error: `Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='abc', input_type=str]` — the top source carries the **exact** badge.

## API

Each project exposes `POST /api/projects/{id}/chat`:

```bash
curl -X POST http://127.0.0.1:8000/api/projects/<id>/chat \
  -H "content-type: application/json" \
  -d '{"question": "How do I make a field optional?", "stream": false}'
```

The full contract is in [`frontend/API.md`](frontend/API.md); interactive docs at
http://127.0.0.1:8000/docs.

## Tests

```bash
cd backend && uv run pytest -q     # 40 tests: contracts, all vector stores, pipeline rules, retrieval
cd frontend && npm run build       # type-check + production build
```

## Layout

```
backend/app/
  core/          node contract + registry, pipeline validation & index hashing, caches, run records
  nodes/         parse, chunk, embed, retrieve, rerank, prompt, generate node types
  vectorstores/  numpy, faiss, chroma, qdrant, lancedb adapters (one contract, one test suite)
  ingest/        loaders, documents, index builds, exact-match keys, background jobs
  engine/        retrieval, chat, store management, sync jobs
  api/           FastAPI routers
frontend/        Vite + React + Tailwind v4 website (API.md = backend contract, DESIGN.md = design spec)
data/            created at runtime: app.db, raw files, caches, vector stores (gitignored)
.claude/agents/  subagent definitions used to build this in parallel
```

## Parallel agents

[`.claude/agents/`](.claude/agents) defines subagents with non-overlapping ownership, so work can
run in parallel: `figma-designer`, `frontend-foundation` (runs first), then `frontend-projects`,
`frontend-configure` and `frontend-playground` in parallel, plus `backend-engineer`,
`qa-tester` and `code-reviewer`. They are picked up when Claude Code starts (or via `/agents`).
