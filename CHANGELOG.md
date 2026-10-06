# Changelog

All notable changes to RAGLabs. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
phases map to releases (`PRD.md` §5).

## [v2.0.0] — 2026-10-06 — Phase 2: Measure & Optimize

### Added

- **Evaluate tab — auto-generated eval sets** (FR-2.1–2.3). Questions are written by the LLM from
  sampled chunks and filtered for validity (a question the model answers closed-book is dropped as
  too generic). Gold labels are `document_id` + a verbatim evidence quote, so one set scores any
  chunking or embedder.
- **Eval-set editing and CSV** (FR-2.4): add, edit, drop, restore and delete questions; CSV export
  and import. Hand-added evidence must be found in the chosen document's chunks.
- **Eval-set revisions and facets** (FR-2.5–2.6): every edit bumps a `revision`; runs record the
  revision they scored, and sets record the corpus fingerprint they were generated from. Each
  question carries 1–4 required facts (facets).
- **Deterministic metrics**: Hit@1/3/k, MRR, nDCG@k, context inclusion, context tokens per query,
  p50/p95 retrieval latency.
- **Optional answer grading** (FR-2.7–2.10): correctness, groundedness, relevancy, specificity and
  facet coverage as discrete verdicts at temperature 0, with a 95% Wilson interval on correctness
  (overlapping intervals are reported as tied). The judge can be any configured provider/model.
- **Failure diagnostics, modes 2–7** (§7.3): every failed question gets exactly one diagnosis, most
  upstream first — `not_retrieved`, `ranked_below_k`, `dropped_by_rerank`, `dropped_by_budget`,
  `incorrect_format`, `incomplete_answer`, `wrong_specificity`, `failed_to_extract` — with a
  plain-English summary and one-click **Apply** fixes for the retrieval modes.
- **Sweeps** (FR-2.15–2.17, 2.20): a grid over up to 4 axes (any `slot.field` / `slot.type`, up to 48
  cells) scored on one eval set, ordered by index hash so cells share cached work; cancel keeps
  finished cells.
- **Auto-Optimize** (FR-2.18): after retrieval-scoring every cell, the top 25% by MRR (at most 5)
  are answer-graded; cells within noise of the leader are judged twice more and take the median
  (FR-2.8).
- **MTEB-seeded embedders** (FR-2.19): local models carry their MTEB retrieval score; the sweep's
  embedder axis is ordered by it with an "MTEB top 3" preset.
- **Leaderboard** (FR-2.21–2.25): sortable table and scatter with the Pareto frontier (MRR vs.
  context tokens), an insight line, and **Promote** — the winner becomes the active version and
  serves the endpoint at once.
- **Cost simulator** (FR-2.33): $/month per configuration from queries/month and your token prices.
- **Regression guard** (FR-2.32): every version saved with a build is scored on the newest ready
  eval set, with ▲/▼ against the previous run.
- **Corpus Health tab** (FR-2.26–2.31): coverage gaps from real questions (Playground/API history
  plus pasted ones) clustered into a ranked content backlog; gaps that a deep top-15 retrieval does
  answer are labelled **retrieval misses** instead. Also duplicates (cosine ≥ 0.97), LLM-confirmed
  contradictions, never-retrieved documents, staleness, and a Markdown export.
- **OKF document metadata** (FR-2.30): `status`, `stale_after`, `verified`, `sources` from Markdown
  front matter or the Documents tab; `usage_count` and last-modified dates are tracked.
- **New pipeline options**: `semantic` chunker; `retrieve.query_expansion` (`multi_query`, `hyde`);
  `retrieve.context_window` (merge neighbouring chunks into each hit).
- **Repo export** (FR-2.34): download any version as a standalone FastAPI project (zip).
- **Smart auto-configuration**: the create wizard analyses the documents (code/table/structure
  density, language, domain) and recommends a pipeline, with the reasoning for each choice.
- **Config-prior instrumentation** (FR-2.35): one anonymised fingerprint row per finished sweep.
- **Demo**: `scripts/seed_demo.py` now also generates an eval set, scores the active version and
  runs an Auto-Optimize sweep (skipped when no LLM key is configured; `--no-eval` for Phase 1 only).

### Changed

- Configure, Playground and Evaluate redesigned; new brand mark. Version activations are logged;
  the Playground offers starter questions.
- The exact-match path no longer counts incidental code-symbol mentions as exact hits (they tied
  and RRF turned the tie order into noise).
- Markdown front matter is read as document metadata and no longer indexed as a chunk. The parser
  revision changed, so existing projects re-parse and rebuild once on their next sync (vectors
  are cached by text, so only changed chunks are re-embedded).
- Repo export now ships a FastAPI server (`app/main.py`: `GET /health`, `POST /chat`), Dockerfile
  and compose file next to the `rag.py` CLI, and honours query expansion and the context window.
- Default Gemini chat model is now `gemini-3.5-flash`: `gemini-2.5-flash` and `-flash-lite` return
  404 "no longer available to new users" for new API keys.

### Known limitations

- `$` cost per query is not measured yet (`cost_usd` is a stub); context tokens per query is the
  deterministic cost proxy.
- No contextual precision/recall judges.
- Not built, deliberately: `unstructured` / `docling` parsers (heavy dependencies) and the semantic
  answer cache (Phase 3). Sweep cells run sequentially (one CPU-bound embedder).
- Eval-set revisions are a counter, not a history table; runs keep their per-item results.
- `fused` still trails `hybrid` slightly on code-heavy docs (MRR 0.885 vs 0.962 on a 13-question
  set) — see `FOLLOW_UPS.md` #1.
- A model download that stalls (e.g. the reranker on first use) has no timeout, so a sweep cell can
  wait indefinitely; cancel the sweep and retry.

## [v1.0.0] — 2026-09-23 — Phase 1: Build & Chat

Tag `v1.0`.

### Added

- Projects (many RAG systems per install) with a 4-step create wizard: name → documents →
  configure → build.
- Upload PDF, DOCX, Markdown, TXT, RST and HTML, or ingest a URL with optional sitemap crawl; raw
  files are kept; per-file parse-quality indicator; tables become atomic chunks.
- Every pipeline stage user-selectable — parse, chunk, embed, vector store, retrieve, rerank,
  prompt, generate — through forms rendered from each node's JSON schema, each parameter marked
  ⚡ instant or 🔁 rebuild.
- Five embedded vector stores: NumPy (exact), FAISS, Chroma, Qdrant (local mode), LanceDB, with an
  exact/approximate badge; switching store never re-embeds (content-addressed caches).
- Dense, keyword (BM25), hybrid and `fused` retrieval, with an exact-match lookup on normalised
  error signatures and code symbols (§6.2); optional local cross-encoder reranking.
- Immutable pipeline versions: list, diff, activate.
- Playground: streaming chat with per-claim citations, a retrieval inspector (per-path scores,
  found-by badges, highlighted cited spans) and a per-step latency/token trace; every turn stored
  as a `Run`.
- `POST /api/projects/{id}/chat` (JSON or SSE), localhost-only, no auth.
- LLMs via the free Gemini and NVIDIA APIs through one OpenAI-compatible adapter.
- Seeded demo project (Pydantic v2 docs).

[v2.0.0]: https://github.com/anurag-njr11/Rag-Builder/compare/v1.0...v2.0
[v1.0.0]: https://github.com/anurag-njr11/Rag-Builder/releases/tag/v1.0
