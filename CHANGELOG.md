# Changelog

All notable changes to RAGLabs. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
phases map to releases (`PRD.md` §5).

## [Unreleased]

### Added

- **"Evaluate a RAG I already have"** in the create wizard: a three-step path (Name, Documents, then Evaluate → Your RAG) that skips Configure and Build.
- **In-app Docs** (top bar → Docs): 20 searchable pages with a sidebar, "on this page" outline and previous/next links, covering every tab, all pipeline options, the metrics and troubleshooting. Written as Markdown in `frontend/src/features/docs/content/`.
- **Bring Your Own RAG** (FR-4.1–4.5): Evaluate → *Your RAG* connects an HTTP endpoint (answer + retrieved passages,
  with a response mapping and an encrypted auth header) and scores it on the same eval set with Hit@k, MRR, nDCG,
  latency and (with a judge) answer grading. It shows up in run history beside pipeline versions. Hits match on
  evidence plus, when the system names a source, the file. Rerank/budget diagnoses and one-click fixes don't apply.
- **`raglabs` CLI** (FR-4.6): `raglabs eval --endpoint … --set eval.csv --min-mrr 0.6` exits non-zero below a
  threshold, for CI; `raglabs serve` runs the app.
- Open-source files: Apache-2.0 `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue/PR
  templates and a CI workflow.

### Removed

- Unused code: `stores.drop_store_files` and the `useHealth`, `useBuilds`, `useJob`, `useNoProviderKey` and `useProjectId` hooks.

## [v3.0.0] — 2026-10-08 — Phase 3: Advanced Retrieval & Trust

### Added

- **Trace timeline** (FR-3.6): every trace step records when it started (`start_ms`, offset from the
  run's start), and the Playground's Trace tab draws steps as a waterfall, so concurrent retrieval
  paths show up side by side. Runs recorded before this keep plain duration bars.
- **Grounding check** (FR-3.5) — a new **Verify** pipeline slot. `grounding_check` makes one extra
  LLM call (the answer's own model, temperature 0) that splits the answer into claims and grades each
  one against the sources. When a claim isn't supported it either flags the answer or retries with
  twice the results and context budget (`max_retries`, default 1). The result is shown under the
  answer, recorded on the run, returned by the API (`verification`) and timed in the trace.
- **Citation-support checking** (FR-3.9): the same call grades each `[n]` citation against the claim
  that cites it; a citation whose source doesn't support its claim is marked in the answer.
- **Grounding check in the Lab** (FR-3.5): answer-graded eval runs and Auto-Optimize answer exactly as
  chat does — check, retry with more context — and report answer p50/p95 latency and the check's pass
  rate. `verify.type` is a sweep axis (with a "Grounding check on vs off" preset); cells that tie on
  retrieval are graded together, since only answer grading tells them apart.
- **Query decomposition** (FR-3.3): `retrieve.query_expansion = decompose` splits a multi-part question
  into sub-questions; each is searched and fused on its own, then they take turns in the top-k so
  every part gets evidence. Ported to repo export.
- **Agentic retriever** (FR-3.1) with **context offloading** (FR-3.2): `retrieve.type = agentic` — the
  plain question is searched, then an LLM planner (step budget 1–6) searches again, reads passages in
  full (offload mode shows it only snippets) and keeps the passages that answer. Every search runs
  through an ordinary retriever, so its trace steps and badges appear as usual. Runs are cached per
  question (any `top_k`), and their cost, tokens and time are always counted uncached. Ported to export.
- **Agentic vs hybrid + rerank on the leaderboard** (FR-3.4): a "vs hybrid + rerank" column (MRR
  difference, token multiple, latency multiple) and insight line, plus an "Agentic vs hybrid + rerank"
  preset. The Pareto cost axis is now `query_tokens` — answer context plus retrieval-side LLM calls —
  so an agentic config no longer looks as cheap as a single search.
- **Semantic answer cache** — a new `cache` slot, checked before retrieval: a near-identical earlier
  question (cosine ≥ threshold) reuses its answer with no retrieval and no LLM call. Numbers and code
  identifiers must match exactly ("top 10" ≠ "top 15"); a hit needs the same config and the same
  documents. Truncated and not-grounded answers aren't cached. Stats and Clear in the Cache stage.
- **Injection-resistance testing** (FR-3.7) and **which defences move it** (FR-3.8): Evaluate →
  Injection resistance plants a poisoned passage at the top of real retrieval results (in memory; the
  corpus is never changed) carrying one of five payloads — instruction override, link exfiltration,
  contact swap, planted false fact, system-prompt leak — each with a canary, so success is a string
  check. Scored per variant: as configured, no defences, each defence alone, all, with 95% intervals.
- **Injection defences**: `prompt.injection_guard` — `data_rule` (default, as before) · `delimited`
  (sources wrapped in `<source>` tags marked untrusted; a smuggled closing tag is escaped) · `none`;
  and `verify.validate_output` — deterministic removal of URLs, emails and phone numbers that appear in
  no source (the answer is then sent whole, never streamed unvalidated). Both ported to export.
- **Embedding adapter** (FR-3.10, 3.12): Evaluate → Embedding adapter trains a query-side linear map on
  the eval set's labels (NumPy, CPU, seconds). λ is chosen by cross-validation inside the training
  questions; it's reported before/after on held-out questions it never saw, and only *recommended*
  when it beats the plain embedder in both. Instant to use (`retrieve.adapter`), skipped with a trace
  note if trained for another embedder, shipped as `data/adapter.npy` in repo export.
- **Prompt optimisation** (FR-3.11, 3.12), DSPy-style without the framework: bootstrapped few-shot
  examples from the model's own best answers, LLM-proposed instruction blocks, selection on val
  questions, before/after on test questions never used to choose. The result lands in
  `prompt.extra_instructions` / `prompt.examples` (also in export).

- **OKF bundles** (FR-3.18, 3.20): Documents → Import OKF reads a zip of Markdown with YAML front matter —
  one document per file (bundle path kept in the name), `type / status / stale_after / verified / generated /
  sources` from the front matter, other files skipped with a reason, missing fields and broken links
  tolerated. Export OKF writes the corpus back as a bundle: text, provenance, trust tier (human / process /
  agent from `verified`), lifecycle, usage, and the latest Corpus Health findings, plus an index.
- **Metadata-aware retrieval** (FR-3.19): `retrieve.okf_policy` leaves out documents past `stale_after`,
  halves the score of `deprecated` ones and prefers better-verified sources on ties. Ported to export.
- **Attested Computation** (FR-3.21): a Data tab for CSV tables and computations — a read-only SQL query
  with typed parameters and declarative checks (rows, columns, non-null, numeric bounds). With the new
  `compute` slot, numeric questions are routed (the model only picks a computation and fills parameters),
  run read-only with a time limit, attested, and answered exactly as computed with a receipt; a failed
  check falls back to the documents with a warning, or refuses. Attesters are declarative rather than
  OKF's Python files, so uploaded code never runs.

- **Production query loop** (FR-3.22): every answer records whether it came from the Playground or the
  API; Corpus Health can use production traffic only; a monitor re-runs the report automatically after
  every N new real questions (checked after each answer, no scheduler); and each report shows its trend
  against the previous one — coverage change, gaps resolved, questions no longer answered, new gaps.

- **API keys and a usage dashboard** (FR-3.23, self-hosted part): the web UI on this machine needs no
  key; any other caller sends `Authorization: Bearer rl_…` — a chat key reaches one project's query
  endpoint only, an admin key the whole API; only a hash is stored. The API tab shows daily requests,
  errors, latency, tokens and cost, by source and by key. `TRUST_LOOPBACK=false` for reverse proxies.
  Team workspaces stay with the hosted edition (`OSS_ROADMAP.md`).

- **Chat-to-build** (FR-3.25): Configure → "Describe a change" turns plain language ("add a reranker and
  switch to hybrid") into a schema-valid draft change — the model only proposes `slot.field` edits, the
  server applies and validates them (one repair round) — shown with ⚡/🔁 badges before you apply it;
  the changed stages (or canvas nodes) light up.
- **Canvas** (FR-3.24): Configure → Canvas draws the pipeline as it actually runs — the query lane with
  its parallel retrieval paths, the index lane feeding them, and the early exits and loops (cache hit,
  attested computation, agent search loop, grounding-check retry). Drag nodes (layout kept per project),
  drop a type from the palette onto its node, toggle retrieval paths, click a node to edit it. Steps keep
  their order: RAGLabs doesn't rewire them into free-form graphs, so every configuration stays comparable.

- **Recipe gallery** (FR-3.26): a Recipes page with seven built-in starting points (fast & cheap,
  hybrid + rerank, technical docs, multi-part questions, agentic research, hardened for production, FAQ
  bot with a cache) and recipes saved from any version. A share link carries the recipe itself, so it
  works on any install; forking into a project drops a corpus-specific adapter and keeps the project's
  own LLM if the recipe's isn't connected, and says so.
- **Config prior** (FR-3.27): predicts settings for a corpus from the sweeps that won on similar corpora
  on this install, with a stated confidence (agreement × amount of evidence × similarity), falling back
  to the rule-based recommender — labelled as such — with no history. Evaluate → Sweeps offers it as a
  preset: verify the prediction against your current settings in one sweep.

- **Code check** (FR-3.13–3.16): `verify.type = execution_check` runs the answer's Python in a throwaway
  Docker container (no network, 256 MB, 1 CPU, 64 processes, read-only root, unprivileged user, time
  limit) against tests, in order of strength: the eval question's own, `>>>` examples from the retrieved
  docs that use the answer's names, or model-written asserts (labelled weaker evidence). A failure goes
  back to the model to fix, up to `max_steps` (3, at most 4), stopping early when the same error repeats;
  if nothing passes the best attempt is shown as unverified. No Docker means no check, never a local run.
  `SANDBOX_IMAGE` picks the image.
- **Execution-verified correctness** (FR-3.17): eval items take optional `tests` (editor, CSV column);
  answer-graded runs report the share of tested questions whose code passed, with a 95% interval. When two
  leaderboard cells both have it, it ranks them before MRR.

### Changed

- Pipelines gained three slots: `verify` (after generate; `none` · `grounding_check` · `execution_check`), `cache` and `compute` (before retrieve). Configs saved
  without them load with `{type: 'none'}`; index hashes are unchanged.
- Batch LLM work (eval answers, judging, attack tests) retries rate limits, timeouts, overloads and 5xx
  with exponential backoff (`ProviderError.retryable`); chat still fails fast.
- Eval latency counts a cached LLM step (query expansion, agent run) at the time it really takes, so
  sweep cells that share the cache aren't scored as faster.

### Fixed

- API tests used a host name the trusted-host middleware rejects; they now use `testserver`.

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
- **Measured cost, index size, contextual precision/recall** (§7.2): LLM calls are priced from a
  paid-tier list-price table (Gemini; NVIDIA publishes none, shown as "—"), so traces show real
  `cost_usd` and eval runs and the leaderboard report **$/1k queries** (query expansion, plus answer
  generation when graded). Eval runs and leaderboard cells report **index size** (chunks, vectors,
  bytes on disk). The existing answer-grading call also returns per-passage relevance and
  per-fact support, giving rank-weighted **contextual precision** and **contextual recall**.
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

- Not built, deliberately: `unstructured` / `docling` parsers (heavy dependencies) and the semantic
  answer cache (Phase 3). Sweep cells run sequentially (one CPU-bound embedder).
- Eval-set revisions are a counter, not a history table; runs keep their per-item results.
- `fused` still trails `hybrid` slightly on code-heavy docs (MRR 0.885 vs 0.962 on a 13-question
  set) — see `FOLLOW_UPS.md` #1.

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
