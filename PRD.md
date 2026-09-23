# RAG Builder — Product Requirements Document

| | |
|---|---|
| **Status** | Draft v1.0 |
| **Last updated** | 2026-09-23 |
| **Owner** | Anurag |
| **Companion doc** | `IDEAS.md` — full idea catalogue, including rejected ideas and rationale |

---

## 1. Problem

Building a RAG pipeline is a solved, commoditised problem. Anyone can wire one up in an
afternoon from a tutorial, and at least five GUI builders already exist (LangFlow, Flowise,
RAGFlow, Dify, and n8n-style tools).

What is *not* solved is everything that happens next:

> **Teams ship RAG systems they cannot evaluate, tuned by guesswork, and they only find out
> it is bad from users.**

Two compounding causes:

**1. The configuration space is large and interacting.** Parser, chunk size, overlap,
chunking strategy, embedding model, dense vs. hybrid, `top_k`, reranker, prompt, verification
— easily 50–100 plausible combinations whose effects are not independent. The only honest way
to choose is to measure, and almost nobody measures, because building an eval set is tedious
and running a sweep needs infrastructure.

**2. The corpus is the bigger lever, and it is invisible.** Chunk size might move quality by
10%. A missing document caps it at zero, forever, and no amount of reranking fixes it. Two
external data points:

- Infosys, reporting from a production deployment: *"in about 70% of these cases, the perceived
  error could be attributed to outdated or incorrect documentation that requires updating."*
- Widely repeated (vendor-sourced, so discount the precision): **~80% of RAG failures originate
  in the ingestion/chunking layer, not the LLM.**

There is no tool that says *"your documentation cannot answer 23% of what users actually ask,
here are the twelve missing topics ranked by query volume."*

### 1.1 Why now

- Auto-generated eval sets are newly practical — an LLM can write `(question, gold answer,
  gold chunk)` triples good enough to rank configurations, which removes the labelling barrier
  that made evaluation a specialist activity.
- The configuration space keeps growing (agentic retrieval, rerankers, new embedding models
  weekly), so the guesswork problem gets worse, not better.
- Standards are emerging for curated knowledge (OKF, June 2026), which gives the "clean up your
  knowledge base" output somewhere to land.

---

## 2. Goals and non-goals

### 2.1 Goals

| ID | Goal |
|---|---|
| G1 | Make measuring a RAG system as easy as building one |
| G2 | Make configuration choices evidence-based rather than vibes-based |
| G3 | Shift the user's attention upstream — from `top_k` to *"can this corpus answer the question at all?"* |
| G4 | Produce artifacts the user owns (a config, a repo, a cleaned knowledge base), not a service they rent |
| G5 | Ship three standalone, fully usable releases rather than one big-bang launch |

### 2.2 Non-goals

| ID | Non-goal | Why |
|---|---|---|
| N1 | Be a better NotebookLM | Google already won it, and it is free |
| N2 | Be a RAG tutorial | A hundred free ones exist; learning arrives as a byproduct of sweeps |
| N3 | Be a connector/ingestion platform | Integration treadmill; that is Glean's game |
| N4 | Permissions-aware enterprise retrieval | Real problem, but an enterprise-sales business — wrong shape |
| N5 | Production-grade infrastructure in Phase 1 | Ceremony while there is one user |
| N6 | Beat Cursor/Copilot as a coding assistant | The code vertical exists to provide *ground truth*, not to compete on agent quality |

### 2.3 Product principles

1. **Every feature must help someone decide something.** Agentic retrieval earns its place by
   becoming a measured leaderboard row, not by being fashionable. A prettier canvas fails this test.
2. **Deterministic first.** Where a signal can be computed with arithmetic instead of an LLM
   judgment, compute it. Reproducibility is the product's credibility.
3. **The corpus outranks the config.** When both could explain a failure, investigate the corpus.
4. **Each phase stands alone.** No release may depend on the next one to be useful.
5. **No framework lock-in.** The user must be able to leave with working code.

---

## 3. Users

| Persona | Situation | Needs | Phase served |
|---|---|---|---|
| **Priya — AI engineer** (primary, P1–P2) | Built a RAG prototype, knows it's mediocre, no idea why | Evidence about which config wins; a diagnosis, not a dashboard | 1, 2 |
| **Marcus — docs / knowledge-ops lead** (primary, P2–P3) | Owns the documentation the bot reads; blamed when it's wrong | A ranked content backlog: gaps, contradictions, stale pages | 2, 3 |
| **Sana — support lead** (secondary, P3) | Wants ticket deflection; needs to know what the bot can't answer | Coverage reporting driven by real user questions | 3 |
| **Dev — solo builder** (secondary, P1) | Wants a working RAG chatbot over their docs today | Upload → chat → endpoint, with no code | 1 |

**Buyer evolution:** Phase 1–2 sells to an engineer solving a one-time tuning task (small,
non-recurring). Phase 2–3 sells to a docs/support owner with a permanent problem and a budget,
where value attaches to ticket deflection rather than to nDCG. **The product's commercial
viability depends on making that transition.**

---

## 4. Positioning

> **Not** *"optimise your RAG config."*
> **Instead:** *"your knowledge base has holes, contradictions and dead weight — here they are,
> ranked, with what to write."*

**Phase stack:**

- **Phase 1** gives you a working RAG chatbot over your docs.
- **Phase 2** tells you whether your config is wrong — *and whether your documentation is.*
- **Phase 3** keeps telling you, from real user questions, forever.

**One-liner:** *"Your RAG isn't bad because of chunk size. It's bad because your docs don't
answer the question. We show you which ones."*

**Headline metric — time to first evidence:** corpus uploaded → leaderboard with a Pareto
frontier, **under five minutes, zero labelled data.** That number is the product.

### 4.1 Competitive position

| Category | Examples | Why we're different |
|---|---|---|
| GUI pipeline builders | LangFlow, Flowise, Dify, RAGFlow | They help you build; none tell you if it's good |
| Eval libraries | Ragas, TruLens, DeepEval | Libraries — you must write eval code before learning anything. No corpus → eval set → sweep → answer path |
| Observability | LangSmith, Langfuse | Trace what happened; don't tell you what to change |
| Enterprise search | Glean | Different problem (connectors, permissions, scale) |

The unserved gap: **a GUI that goes corpus → eval set → sweep → decision, with no labelled data.**

---

## 5. Phase overview

| Phase | Name | Deliverable | Effort |
|---|---|---|---|
| **1** | Build & Chat | Full website: create RAG projects, upload docs, choose and tune every parameter (incl. 5 embedded vector databases), chat with cited answers and a retrieval inspector, local API. No Docker. | 7.5–8 days |
| **2** | Measure & Optimize | Auto eval sets, sweeps, Pareto leaderboard, Auto-Optimize, 7-mode diagnostics, Corpus Health, regression guard, repo export. | 10–12 days |
| **3** | Advanced & Trust | Agentic retrieval, query decomposition, grounding check, trace view, injection-resistance testing, embedding adapter, DSPy, production query loop, full canvas, platform. | 12–15 days |

**Release gate — identical for every phase:**

- Clean-machine install and run, verified from the README alone
- Seeded demo project demonstrating the phase's headline feature in under 2 minutes
- README updated with the new capability and a GIF
- Tagged release (`v1.0` / `v2.0` / `v3.0`) + CHANGELOG entry
- **Previous phase's happy path still works** — smoke-tested before tagging

---

## 6. Phase 1 — Build & Chat

**Goal:** a complete, usable no-code RAG system. Someone uploads docs and walks away with a
working cited-answer endpoint.

**Explicitly excluded:** evaluation, sweeps, agentic retrieval, multi-tenancy, auth, Docker,
Postgres, Celery, repo export, embeddable widget, server-based vector DBs.

**Revised during planning (2026-09-23):** Phase 1 is a full website with *projects* (many RAG
systems per install), a create wizard, and **every pipeline parameter user-selectable —
including the vector database**. Five embedded stores ship (NumPy exact, FAISS, Chroma,
Qdrant local mode, LanceDB), each with its own index parameters and an exact/approximate
badge. Each parameter is marked ⚡ instant or 🔁 rebuild; switching store never re-embeds.
LLMs are the free **Gemini** and **NVIDIA** APIs via one OpenAI-compatible adapter.

### 6.1 Functional requirements

**Corpus**

| ID | Requirement |
|---|---|
| FR-1.1 | Upload PDF, DOCX, MD, TXT, HTML via drag-and-drop or file picker |
| FR-1.2 | Ingest from a URL, with optional sitemap crawl (depth-limited) |
| FR-1.3 | **Store the raw original file** on disk, indefinitely, keyed to its document record |
| FR-1.4 | Parse → chunk → embed → index, with live progress streamed over SSE |
| FR-1.5 | Per-file parse-quality indicator (extracted char count, detected tables, OCR fallback triggered, empty-page count) |
| FR-1.6 | **Detect tables and emit them as atomic chunks** (Markdown/CSV) that are never split |
| FR-1.7 | Delete a document → remove its chunks and vectors, using the raw file as reference |
| FR-1.8 | Re-ingest on config change, served from the content-addressed cache when inputs are unchanged |

**Pipeline**

| ID | Requirement |
|---|---|
| FR-1.9 | Pipeline is a JSON document conforming to a published schema (§10) |
| FR-1.10 | Edit each node through a form auto-rendered from that node's JSON-schema fragment |
| FR-1.11 | Node types in Phase 1: `parse`, `chunk`, `embed`, `index`, `retrieve`, `rerank`, `prompt`, `generate` |
| FR-1.12 | Chunking strategies: fixed, recursive, **structure-aware (Markdown heading-aware)** |
| FR-1.13 | Retrieval: dense, hybrid (dense + BM25/FTS5), and **`fused`** — dense + exact-match via RRF |
| FR-1.14 | **Exact-match lookup path**: SQLite FTS5 + exact-match table keyed on normalised signature (§6.2) |
| FR-1.15 | Every edit creates a new immutable pipeline version; list, diff and roll back |
| FR-1.16 | Optional read-only node graph as navigation — click a node, edit in the side panel |

**Playground**

| ID | Requirement |
|---|---|
| FR-1.17 | Streaming chat against any pipeline version |
| FR-1.18 | Answers carry per-claim citations linked to source chunks |
| FR-1.19 | **Retrieval inspector**: retrieved chunks with scores, retrieval path (dense/exact/fused), source document and page, highlighted span |
| FR-1.20 | Per-turn tokens, cost and latency, broken down by step |
| FR-1.21 | Every turn writes a `Run` record with its full trace-event list |

**API**

| ID | Requirement |
|---|---|
| FR-1.22 | `POST /api/chat` — accepts a question + pipeline version, returns answer + citations + trace |
| FR-1.23 | No auth in Phase 1; bind to localhost by default |

### 6.2 Error-signature normalisation (FR-1.14)

Exact lookup is useless without normalisation. Before keying, strip:

- Memory addresses (`0x7f8b...`)
- Absolute file paths and line numbers
- Quoted literals and user identifiers
- Timestamps and UUIDs

So that `'NoneType' object has no attribute 'get'` and `'NoneType' object has no attribute
'items'` collapse to a single template. **The normalisation step is most of the value of the
exact path.**

### 6.3 Definition of done

Clone → `pip install -r requirements.txt` → `npm install` → two run commands → upload a
100-page PDF → receive a cited answer in the playground with a populated inspector →
`curl` the endpoint successfully. Seeded demo corpus included. README with a GIF.

---

## 7. Phase 2 — Measure & Optimize

**Goal:** the differentiator. Phase 1 users gain new tabs; nothing they had breaks.

### 7.1 Eval sets

| ID | Requirement |
|---|---|
| FR-2.1 | Generate `(question, gold_answer, gold_chunk_id)` triples by sampling chunks and prompting an LLM |
| FR-2.2 | **Validity filter** — attempt to answer each question with no context; discard if answered correctly (too generic) |
| FR-2.3 | Target 50–100 valid triples in under 2 minutes |
| FR-2.4 | Manual add / edit / delete; CSV import and export |
| FR-2.5 | Eval sets are versioned and bound to a corpus version |
| FR-2.6 | Facet-annotate gold answers (list of required facts) to support the *incomplete answer* diagnostic |

### 7.2 Metrics

**Deterministic (headline — exactly reproducible):**

| Metric | Definition |
|---|---|
| Hit-rate@k | Fraction of questions whose `gold_chunk_id` appears in top-k |
| MRR | Mean reciprocal rank of the gold chunk |
| nDCG@k | Normalised discounted cumulative gain |
| Gold rank | Absolute rank of the gold chunk (drives the *overlooked* diagnostic) |
| Context inclusion | Whether the gold chunk survived into the final assembled context |
| p50 / p95 latency | Per config |
| Cost per 1k queries | From the `Run` cost ledger |
| Index size | Chunks, vectors, bytes |

**LLM-judged (secondary — noisy, always reported with a confidence interval):**

Faithfulness, answer relevancy, contextual relevancy, contextual precision, contextual recall.

| ID | Requirement |
|---|---|
| FR-2.7 | Judge scores must be **discrete ordinals** via structured outputs, never free floats |
| FR-2.8 | Judge is run 3× with the **median** taken when a config sits near a decision boundary |
| FR-2.9 | Report confidence intervals; mark configs with overlapping intervals as **tied**, not ranked |
| FR-2.10 | The leaderboard's default sort is a **deterministic** metric |

> **Constraint:** judge scores are never bit-reproducible. Phase 1 uses Gemini/NVIDIA, which
> **do** accept `temperature=0` — that lowers judge variance, but hosted models still aren't
> bit-exact across runs. (Current Claude models removed `temperature` entirely, so a Claude judge
> could not even be pinned.) This is why deterministic metrics lead.

### 7.3 The 7-mode failure taxonomy

Classification is **deterministic** for modes 1–4 and 7, because the eval set carries
`gold_chunk_id`.

| # | Mode | Detection | Prescribed fix |
|---|---|---|---|
| 1 | **Lack of content** | No chunk anywhere contains the answer / nothing clears the similarity floor | **Corpus gap** → content backlog |
| 2 | **Overlooked top-ranked doc** | Gold chunk ranks at position *n > k* | Raise `top_k`, add/improve reranker |
| 3 | **Consolidation loss** | Gold chunk in top-k but absent from the final context | Fix truncation/packing budget |
| 4 | **Failure to extract** | Gold chunk present in final context, answer still wrong | Prompt/model; reduce context noise |
| 5 | **Incorrect format** | Structured-output validation fails | Format constraint in prompt |
| 6 | **Inappropriate specificity** | Length/detail heuristic vs. gold (judge-assisted) | Prompt tuning |
| 7 | **Incomplete answer** | Count gold-answer facets present in the response | Enable query decomposition |

| ID | Requirement |
|---|---|
| FR-2.11 | Classify every failed eval question into exactly one mode, most-upstream-wins |
| FR-2.12 | Split the diagnostics view into **pipeline failures** (2–7) and **corpus failures** (1) |
| FR-2.13 | Each mode shows a prescribed fix with a one-click **Apply** that mutates the pipeline JSON |
| FR-2.14 | Surface a plain-English summary: *"31% of failures are chunk-boundary splits."* |

### 7.4 Sweeps

| ID | Requirement |
|---|---|
| FR-2.15 | Select axes and ranges; generate the cartesian grid; cap by a user-set budget (cells or time) |
| FR-2.16 | Execute cells in parallel with live progress (per-cell status grid) |
| FR-2.17 | **Content-addressed cache** keyed by config hash at every stage (§11.2) — mandatory, not an optimisation |
| FR-2.18 | **Auto-Optimize**: successive halving — score all candidates on deterministic retrieval metrics, promote top ~25% to LLM judging |
| FR-2.19 | Seed embedder candidates from MTEB rankings rather than an arbitrary list |
| FR-2.20 | Cancel a running sweep; partial results remain valid and visible |

**Phase 2 sweep axes**

```
parser     ∈ {pymupdf, pdfplumber, unstructured, docling, ocr}
chunker    ∈ {fixed, recursive, structure_aware, semantic}
chunk_size ∈ {256, 512, 1024}
overlap    ∈ {0, 64, 128}
embedder   ∈ {MTEB-seeded candidate list}
retriever  ∈ {dense, hybrid, sentence_window, auto_merging, multi_query, hyde}
lookup     ∈ {semantic, exact, fused}
top_k      ∈ {3, 5, 10}
reranker   ∈ {off, bge-reranker-base}
cache      ∈ {off, semantic@0.95}
```

### 7.5 Leaderboard

| ID | Requirement |
|---|---|
| FR-2.21 | Sortable table of every evaluated config with all metrics |
| FR-2.22 | Scatter plot of quality vs. cost-per-query with the **Pareto frontier** drawn |
| FR-2.23 | Click a point → config detail → **Promote to production** |
| FR-2.24 | Auto-generated insight line, e.g. *"Reranking added 14% faithfulness for +180ms and +$0.4/1k queries."* |
| FR-2.25 | Promoted config immediately serves the published endpoint |

### 7.6 Corpus Health

| ID | Requirement |
|---|---|
| FR-2.26 | **Coverage gaps** — cluster mode-1 failures into topics, rank by frequency, present as a content backlog |
| FR-2.27 | **Contradictions** — scan embedding neighbourhoods for near-duplicates, LLM-check pairs for contradiction, list with both sources |
| FR-2.28 | **Staleness** — flag documents past `stale_after` or with an old last-modified date |
| FR-2.29 | **Dead weight** — chunks never retrieved by any eval question |
| FR-2.30 | Adopt OKF field names (`status`, `stale_after`, `verified`, `sources`, `usage_count`) as optional chunk/document metadata |
| FR-2.31 | Export the corpus-health report as CSV/Markdown |

### 7.7 Supporting

| ID | Requirement |
|---|---|
| FR-2.32 | **Regression guard** — re-run the eval set on every pipeline edit; show a diff vs. the promoted version |
| FR-2.33 | **Cost simulator** — projected monthly cost per config at a user-supplied query volume |
| FR-2.34 | **Repo export** — render the pipeline JSON to a working FastAPI project (`app/`, `requirements.txt`, Dockerfile, compose, README); download as zip |
| FR-2.35 | **Config-prior instrumentation** — log corpus fingerprint + winning config + score per sweep, anonymised, for future use (§8.6) |

### 7.8 Definition of done

Upload corpus → generate eval set → Auto-Optimize → leaderboard with a Pareto frontier →
promote the winner → published endpoint serves it → diagnostics names the dominant failure
mode in plain English → Corpus Health lists at least one real gap → repo export runs standalone.

---

## 8. Phase 3 — Advanced Retrieval & Trust

Items here are **independently shippable**; release them as increments rather than one drop.

### 8.1 Advanced retrieval

| ID | Requirement |
|---|---|
| FR-3.1 | **Agentic retriever** node: plan → search → read → synthesize, with a configurable step budget |
| FR-3.2 | **Context offloading** flag — write retrieved chunks to a store, pass references, sub-agents read individually |
| FR-3.3 | **Query decomposition** — split multi-hop questions, retrieve per sub-query, merge |
| FR-3.4 | All of the above become sweep axes; the leaderboard reports quality delta, cost multiple and latency multiple vs. `hybrid+rerank` |

### 8.2 Trust and verification

| ID | Requirement |
|---|---|
| FR-3.5 | **Grounding-check node** in the request path: grade answer against context, `on_fail: retry_with_more_context`, `max_retries: 1` |
| FR-3.6 | **Trace view** — step-by-step timeline with tokens/latency/cost per step. **Mandatory**; agentic configs are unreadable without it |
| FR-3.7 | **Injection-resistance testing** — inject canary documents with payloads, run the eval set, report an Injection Resistance score per config |
| FR-3.8 | Show which defences move that score: source prefixing, data-treatment framing, grounding check, output validation |
| FR-3.9 | **Citation-support checking** — verify each cited span actually supports the claim attached to it |

### 8.3 Learned optimisation

| ID | Requirement |
|---|---|
| FR-3.10 | **Embedding adapter** — train a linear projection over frozen embeddings with contrastive loss, using the auto-generated eval set as labelled pairs. Report before/after recall |
| FR-3.11 | **DSPy prompt optimisation** against the same eval set; report before/after and show the optimised prompt |
| FR-3.12 | Both artifacts are per-corpus, versioned, exportable, and includable in repo export |

### 8.4 Code vertical (optional track)

| ID | Requirement |
|---|---|
| FR-3.13 | **Validation loop** — generate code → execute in sandbox → run tests → self-correct |
| FR-3.14 | Test source priority: library's own suite → doctests in retrieved docs → generated tests (labelled as weaker evidence) |
| FR-3.15 | Governors: step cap 3–4, no-progress detector (same failing test twice → stop), honest *"couldn't verify"* outcome |
| FR-3.16 | Sandbox isolation: container, no network, memory cap, timeout |
| FR-3.17 | **Execution-verified correctness** becomes a first-class eval metric — deterministic, and leads the leaderboard where available |

> The code vertical exists to supply **deterministic ground truth** that prose RAG cannot.
> It is not an attempt to compete with Cursor/Copilot/Claude Code.

### 8.5 Knowledge format

| ID | Requirement |
|---|---|
| FR-3.18 | **OKF bundle import** — read `type`, `sources`, `generated`, `verified`, `status`, `stale_after`; tolerate missing fields, unknown types, broken links per spec |
| FR-3.19 | Use OKF metadata in retrieval — down-rank `status: deprecated`, filter past `stale_after`, prefer human-reviewed on ties |
| FR-3.20 | **OKF bundle export** — emit the cleaned corpus as a conformant bundle with provenance and trust tiers |
| FR-3.21 | **Attested Computation** node — numeric queries route to a sanctioned computation, executed read-only, verified by a deterministic attester; display gated on the verdict |

### 8.6 Platform and loop

| ID | Requirement |
|---|---|
| FR-3.22 | **Production query ingestion** — feed real endpoint queries back into gap detection |
| FR-3.23 | Multi-tenant projects, team members, usage dashboard, API keys |
| FR-3.24 | Full drag-and-drop canvas with branching pipelines |
| FR-3.25 | **Chat-to-build** — natural-language edit → schema-valid JSON patch → canvas animates the change |
| FR-3.26 | Recipe gallery — share/fork pipeline configs by URL |
| FR-3.27 | **Config prior** — predict a winning config from corpus fingerprint, with a stated confidence and an offer to verify by sweep |

---

## 9. Architecture

### 9.1 Phase 1 (deliberately minimal)

```
Vite + React SPA  ──REST / SSE──▶  FastAPI (uvicorn)
  Tailwind v4                          │
  TanStack Query                       ├── SQLite (aiosqlite)   projects, documents, versions, builds,
  React Router                         │                        chunks, vector cache, runs, traces
                                       ├── SQLite FTS5          keyword (BM25) + exact-match lookup
                                       ├── Vector store         NumPy | FAISS | Chroma | Qdrant (local) | LanceDB
                                       │                        one folder per build: data/stores/{project}/{build}
                                       ├── data/raw, data/cache raw files, parsed/chunk artifacts, models
                                       ├── fastembed (ONNX)     local embeddings + cross-encoder rerankers
                                       ├── Gemini / NVIDIA      OpenAI-compatible chat + embeddings
                                       └── asyncio jobs         index builds + SSE progress
```

No Docker, no Postgres, no Redis, no Celery, no object store, no auth. Keyword and exact search
live in SQLite for every store, so hybrid/fused retrieval behaves identically whichever vector
DB is chosen — store comparisons stay fair.

### 9.2 Infrastructure evolution triggers

Add each piece **when its trigger fires**, not on a schedule:

| Add | Trigger |
|---|---|
| Server vector DBs (pgvector, Elasticsearch, Milvus, Weaviate) | Needed scale or sharing; each is one store adapter + a connection string, and needs Docker. Milvus Lite is skipped — no Windows support |
| Background worker (Celery / arq) | Ingest or sweep exceeds ~60s and blocking requests becomes annoying — likely early Phase 2 |
| Docker Compose | Someone other than you needs to run it |
| Object storage | Raw files outgrow local disk, or air-gapped model caching is needed |
| API keys + auth | Exposed beyond localhost |
| Multi-tenancy | Phase 3, if ever |

> **Exact stores stay the default for comparisons.** NumPy, FAISS Flat, Qdrant local mode and
> LanceDB without an index are exact and return identical rankings (enforced by tests). ANN
> indexes (HNSW/IVF) are approximate — the UI badges them so users know before comparing runs.

### 9.3 Frontend choice

Vite + React (not Next.js, not Streamlit). Next.js adds SSR and routing complexity the product
does not need. Streamlit would ship in two days and then be discarded entirely — the canvas,
retrieval inspector and leaderboard all fight it.

---

## 10. The pipeline document

**Everything hinges on one idea: a pipeline is a JSON document, not code.** The canvas edits
it, the runtime executes it, the sweeper mutates it, the exporter renders it to code, and each
leaderboard row *is* one of these plus a score.

```json
{
  "parse":        { "type": "pymupdf4llm", "strip_headers_footers": true },
  "chunk":        { "type": "structure_aware", "size": 1000, "overlap": 150, "unit": "chars",
                    "heading_depth": 3, "include_heading_in_text": true, "min_chunk_size": 0 },
  "embed":        { "type": "fastembed", "model": "BAAI/bge-small-en-v1.5", "normalize": true,
                    "doc_prefix": null, "query_prefix": null, "batch_size": 32 },
  "vector_store": { "type": "faiss", "metric": "cosine", "index_type": "Flat", "nlist": 64,
                    "nprobe": 8, "hnsw_m": 32, "ef_construction": 200, "ef_search": 64 },
  "retrieve":     { "type": "fused", "top_k": 8, "fusion": "rrf", "rrf_k": 60, "candidates": 40,
                    "dense_weight": 1.0, "keyword_weight": 1.0, "exact_weight": 1.5,
                    "min_score": 0.0, "mmr": false, "mmr_lambda": 0.7 },
  "rerank":       { "type": "none" },
  "prompt":       { "type": "cited_qa", "max_context_tokens": 4000, "say_dont_know": true,
                    "source_labels": true },
  "generate":     { "type": "gemini", "model": "", "temperature": 0.2, "top_p": 1.0, "max_tokens": 1024 }
}
```

This is the recommended Phase 1 default (`GET /api/pipelines/recommended`). A Phase 3 `verify`
slot (grounding check) slots in the same way.

**Rules:**

- Node behaviour lives in a **registry** on the backend, never in the frontend
- Each node type publishes a JSON-schema fragment; the UI auto-renders its form from that
- Adding a node type = register a class + a schema fragment. Nothing else changes
- Pipeline versions are immutable; edits create new versions

---

## 11. Load-bearing engineering decisions

These four cost almost nothing in Phase 1 and prevent rewrites in Phases 2–3. **Skipping any
one turns the corresponding later phase into a refactor.**

### 11.1 Nodes take a context with `emit`, and return a result

```python
class Node:
    async def run(self, ctx: RunContext, inp): ...
    # inside: ctx.emit("search", query=q, tokens=n, ms=t, cost=c)
```

Phase 1 nodes emit once and return. Phase 3's agentic retriever emits forty times and still
returns. Same signature, no runtime rewrite — and the Phase 3 trace view becomes a rendering of
events already being collected.

### 11.2 Content-addressed caching

```
chunks[hash(parse_cfg + chunk_cfg + corpus_version)]
vectors[hash(chunks_hash + embed_cfg)]
```

In Phase 1 this makes re-ingest instant when only `top_k` changes. In Phase 2 it is the
difference between a 72-cell sweep doing ~6 embedding passes and doing 72. **Retrofitting it
later means touching every node.**

### 11.3 `Run` records with a cost ledger

Every execution — including Phase 1 playground turns — writes a `Run` row with its trace
events, tokens, latency and cost per step.

Phase 2's metrics and Phase 3's trace view then become `SELECT`s rather than new instrumentation.
This also catches real bugs: Infosys's cost module revealed `ConversationalRetrievalChain` was
silently making two LLM calls per question — double billing, invisible in code.

### 11.4 Async execution from day one

Infosys hit blocking LLM calls in LangChain: at 50 concurrent users, average response time went
to **180 seconds** with requests processed sequentially; **~9 seconds** after switching to async.

The sweep runner has the identical failure shape. Make node execution async in Phase 1 or Phase 2
sweeps will crawl and be misdiagnosed as "sweeps are just slow".

### 11.5 Also

- **Store raw files forever** — needed to re-ingest on every sweep cell, and for deletion
- **Provider abstraction** — wrap model providers behind one interface so hosted → local (Ollama/Qwen) swaps don't break anything
- **No LangChain/LlamaIndex as a dependency** — hidden costs, hidden blocking, and it undercuts the "export a repo you own" promise

---

## 12. Data model (Phase 1)

As built (`backend/app/schema.sql`):

| Table | Key fields |
|---|---|
| `projects` | `id`, `name`, `description`, `active_version_id`, `created_at` |
| `documents` | `id`, `project_id`, `filename`, `source_url`, `mime`, `raw_path`, `content_sha`, `size_bytes`, `status`, `error`, `parse_quality`, `created_at` |
| `pipeline_versions` | `id`, `project_id`, `version`, `config`, `index_config_hash`, `parent_id`, `note`, `created_at` — immutable |
| `index_builds` | `id`, `project_id`, `index_config_hash`, `config`, `store_type`, `store_path`, `status`, `dim`, `chunk_count`, `stats` — one per (project, rebuild-relevant config); versions differing only in instant params share a build |
| `build_documents` | `build_id`, `document_id`, `chunk_count`, `error` — which documents a build has indexed |
| `chunks` | `id` (deterministic), `build_id`, `document_id`, `ordinal`, `text`, `text_sha`, `token_count`, `is_table`, `page_start`, `page_end`, `heading_path` |
| `chunks_fts` | FTS5 over chunk text (keyword search) |
| `lookup_index` | `build_id`, `chunk_id`, `document_id`, `kind` (signature/symbol), `key` (normalised) |
| `vector_cache` | `text_sha`, `embed_key`, `dim`, `vector` — content-addressed; switching store never re-embeds |
| `runs` / `trace_events` | per chat turn: answer, status, totals / per step: ms, tokens, cost, payload |

Parsed documents and chunk lists are cached as JSON under `data/cache/artifacts`, keyed by
content hash + config.

Phase 2 adds `eval_sets`, `eval_items`, `eval_results`, `sweeps`, `sweep_cells`,
`diagnostics`, `corpus_findings`, `sweep_fingerprints`.

---

## 13. Success metrics

| Metric | Target | Phase |
|---|---|---|
| Time to first cited answer (upload → answer) | < 3 min for a 100-page PDF | 1 |
| **Time to first evidence** (upload → Pareto leaderboard) | **< 5 min** | 2 |
| Eval-set generation | 50–100 valid triples in < 2 min | 2 |
| Sweep throughput | 40-cell sweep in < 90s on demo corpus (cache warm) | 2 |
| Diagnostic reproducibility | 100% identical classification across repeat runs | 2 |
| Corpus findings | ≥ 1 genuine gap or contradiction found on a real corpus | 2 |
| Agentic verdict | Leaderboard quantifies agentic vs. hybrid+rerank quality/cost/latency | 3 |
| Injection resistance | Score measurably improves with defences enabled | 3 |
| Embedding adapter | Measurable recall@5 improvement with zero manual labelling | 3 |

---

## 14. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Sweep too slow to be usable | Kills the headline metric | Content-addressed cache (mandatory), async execution, fast mode sampling 20 questions, cap at 90s |
| LLM judge cost/latency | Sweeps become expensive | Deterministic metrics first; judge only the promoted top 25%; prompt-cache the rubric; batch |
| Judge non-determinism undermines trust | Leaderboard looks arbitrary | Deterministic metrics lead; discrete ordinal judging; median-of-3; confidence intervals; explicit ties |
| Generated eval questions are low quality | Everything downstream is garbage | Validity filter; manual edit; show the eval set openly; facet annotation |
| Canvas eats the schedule | Lab slips | Lab before canvas; canvas is read-only in Phase 1 and the first thing cut |
| Parsing produces garbage | Silent wrong answers | Parse-quality indicator, OCR fallback, atomic table chunks, parser as a swept axis |
| Scope creep into agents/enterprise | Never ships | Non-goals in §2.2 are binding; Phase 3 items ship independently |
| Corpus-health pivot drifts back to pure eval | Loses the commercial thesis | Corpus failures get their own tab and their own report, not a subsection of diagnostics |
| Local models weak at long tool loops (code vertical) | Disappointing Phase 3 demo | Short loops, narrow steps, hosted fallback switch |
| Flywheel/moat never materialises | No defensibility | Instrument from Phase 2, but never plan around it |

---

## 15. Open questions

1. **Vertical first or horizontal first?** The code vertical gives deterministic ground truth
   but narrows the audience. Decide before Phase 2's demo corpus is chosen.
2. **Who is the Phase 2 design target — Priya or Marcus?** Determines whether the home screen
   is the leaderboard or the corpus-health report.
3. **Is repo export or hosted endpoint the primary deliverable?** §2.2 G4 says export; revisit
   if users prefer hosting.
4. **How much OKF to commit to at v0.2?** Currently: borrow field names in Phase 2, full
   import/export in Phase 3. Revisit if adoption stalls.
5. **Semantic chunking cost** — LLM-based chunking breaks the deterministic-chunker assumption
   and the cache key. Needs a design decision before FR-2.15 lists it as an axis.

---

## 16. Glossary

| Term | Meaning |
|---|---|
| **Cell** | One configuration evaluated within a sweep |
| **Config prior** | Model predicting a winning config from a corpus fingerprint |
| **Corpus fingerprint** | Summary features of a corpus (doc types, lengths, structure density, domain, language) |
| **Gold chunk** | The chunk an eval question was generated from; ground truth for retrieval metrics |
| **OKF** | Open Knowledge Format — Google Cloud spec (June 2026) for curated knowledge as Markdown + YAML frontmatter |
| **Pareto frontier** | Configs not dominated on both quality and cost |
| **Promote** | Make a pipeline version the one served by the endpoint |
| **RRF** | Reciprocal Rank Fusion — merges ranked lists without score calibration |
| **Time to first evidence** | Upload → leaderboard with a Pareto frontier |
| **Trace event** | One emitted step record within a run |
