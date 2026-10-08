# RAGLabs

Build your own "chat with your documents" assistant from a web UI — no code.
Upload documents, choose and tune every part of the pipeline (including the vector database),
build the index, and chat with answers that cite their sources. An inspector shows which
passages were found, by which search path, and what each step cost.

**Measure it, too:** test questions written from your own documents, sweeps into a
quality-vs-cost leaderboard, and a content backlog of what your documents can't answer.

**v3.0** — **Phase 1 (Build & Chat)**, **Phase 2 (Measure & Optimize)** and **Phase 3 (Advanced
Retrieval & Trust)** are complete; see [`CHANGELOG.md`](CHANGELOG.md). [`PRD.md`](PRD.md) has the full plan (§7.0: what Phase 2 built)
and [`IDEAS.md`](IDEAS.md) the idea catalogue.

## Measure & optimize (v2.0)

- **Evaluate** — generate an eval set from your documents in one click; score any version on
  Hit@k, MRR, nDCG, context tokens and p50/p95 latency, optionally with LLM-graded answers
  (95% intervals, ties reported as ties). Every miss gets one diagnosis with a suggested fix.
- **Sweeps & Auto-Optimize** — grid over up to 4 settings (chunking, embedder, retriever, top k,
  reranker, query expansion…); Auto-Optimize answer-grades the best quarter. The leaderboard draws
  the quality-vs-cost Pareto frontier and **Promote** makes the winner the live version.
- **Corpus Health** — real user questions → a ranked backlog of what the documents can't answer
  (vs. what retrieval merely missed), plus duplicates, contradictions, unused and stale documents.

## Advanced retrieval & trust (v3.0)

- **Agentic retrieval & query decomposition** — an LLM planner searches again and keeps what answers;
  multi-part questions are split and fused. Both are sweep axes, so you can see whether they pay for
  their extra tokens and latency.
- **Grounding check** — every claim and citation in an answer is graded against its sources; an
  unsupported claim flags the answer or retries with more context.
- **Injection-resistance testing** — plant poisoned passages in real retrieval results and measure
  which defences stop them.
- **Embedding adapter & prompt optimisation** — train a query-side map and DSPy-style few-shot
  prompts on your eval set, with held-out before/after numbers.
- **Platform** — OKF bundle import, code vertical, attested computation, production-query loop,
  API keys with usage, chat-to-build and recipes.

## What you can tune

| Stage | Options |
|---|---|
| Parse | PyMuPDF4LLM (Markdown + tables), PyMuPDF (plain text, optional OCR), pypdf |
| Chunk | fixed, recursive, sentence packing, structure-aware (headings), semantic (embedding breakpoints) — size, overlap, unit… Tables are never split. |
| Embed | local fastembed models (bge-small/base, MiniLM, arctic, nomic, mxbai) or Gemini / NVIDIA APIs |
| Vector store | NumPy (exact), FAISS (Flat / IVF / HNSW), Chroma, Qdrant (local mode), LanceDB (none / IVF / PQ / HNSW) |
| Retrieve | dense, keyword (BM25), hybrid, fused (+ exact error-message/code-symbol matching); RRF or weighted fusion, MMR, thresholds; query expansion (multi-query, HyDE); neighbouring-chunk context window |
| Rerank | off, or local cross-encoders |
| Prompt | cited answer, concise, detailed, or your own template; context budget |
| Generate | any OpenAI-compatible LLM: Gemini, NVIDIA, OpenAI, Anthropic, Groq, Mistral, OpenRouter, Together, DeepSeek, Ollama, LM Studio, or your own endpoint (vLLM, LiteLLM, a gateway…); model, temperature, top-p, max tokens |

Every parameter is labelled **⚡ instant** (applies at query time) or **🔁 rebuild** (needs
re-indexing). Rebuilds reuse cached work: switching vector store never re-embeds.
Every saved configuration is an immutable version you can diff and switch back to at any time.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python is fetched automatically — the backend uses 3.12)
- Node.js 20+
- An LLM for chatting (retrieval and the inspector work without one): a free
  [Gemini](https://aistudio.google.com/apikey) or [NVIDIA](https://build.nvidia.com) key, a key for
  any other supported provider, or a local server such as Ollama. Connect it in the app under
  **LLM providers**, or via `.env`.

## Security of API keys

- Keys entered in the app are encrypted at rest (AES-256-GCM). The master key is created
  on first run in your user config directory, **not** in `data/`, so a copied database
  can't be read on its own. Back it up, or supply your own via `RAGLABS_SECRET_KEY`
  (see `.env.example`).
- Keys are never returned by the API (only `…abcd`), are scrubbed from logs, error
  messages and run history, and are never written into exports.
- A stored key is only ever sent to the base URL it was saved with. Changing the URL
  means re-entering the key.
- The backend only answers to `localhost`/`127.0.0.1` Host headers (`ALLOWED_HOSTS`),
  which blocks DNS-rebinding attacks from web pages.

## Run it

```bash
cp .env.example .env          # optional: paste e.g. GEMINI_API_KEY / OPENAI_API_KEY (or add keys in the UI)

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

## Test a RAG you already have

Evaluate → **Your RAG** connects any HTTP endpoint (`POST {"question"}` → `{"answer", "contexts": [{"text", "source"}]}`, mappable) and scores it on the same eval set as your pipelines, so you can see
"your RAG: MRR 0.52, best RAGLabs config: 0.71". See [`USER_GUIDE.md`](USER_GUIDE.md).

### Gate CI on retrieval quality

```bash
cd backend && uv run raglabs eval --endpoint https://staging.example.com/ask --set eval.csv   --header "Authorization: Bearer $RAG_TOKEN" --min-mrr 0.6 --min-hit 0.8
```

`eval.csv` has columns `question`, `evidence` (a verbatim quote that answers it) and optionally `document`
(the file name). Exit code 0 = thresholds met, 1 = missed, 2 = bad input or unreachable. `--json` prints the metrics.
In GitHub Actions, run the command above in a step after `astral-sh/setup-uv`. `raglabs serve` starts the app.

## Tests

```bash
cd backend && uv run pytest -q     # 240+ tests: contracts, all vector stores, pipeline rules, retrieval, eval, answer grading, sweeps, corpus health, eval-set editing
cd frontend && npm run build       # type-check + production build
```

## Contributing & license

See [`CONTRIBUTING.md`](CONTRIBUTING.md) (how to add a node type, vector store or LLM preset). Licensed under [Apache-2.0](LICENSE).

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
