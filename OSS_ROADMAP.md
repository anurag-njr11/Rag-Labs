# RAGLabs — Open Source, Bring Your Own RAG, and the SaaS Path

> **Status: Deferred. Starts after Phases 1–3 (PRD.md) are complete.**
> Drafted 2026-10-07. Companion to `PRD.md` and `IDEAS.md`.

---

## Context
Target audience shifts to **developers** building/evaluating RAG, distributed as **open source on GitHub**
(community contributions), with a **SaaS later** once adoption exists. User's headline feature request:
**let developers connect their own RAG system and test it inside RAGLabs.**

This is a good fit and it fixes a real weakness: today every metric assumes the RAG *is* a RAGLabs
pipeline. Most developers already have a RAG (LangChain, LlamaIndex, custom). They won't rebuild it
in our GUI just to measure it. BYO-RAG turns RAGLabs from "another builder" into "the eval harness for
whatever you built" — exactly the gap the PRD names (§4.1: eval libs need code, builders don't measure).

Key code fact: retrieval scoring is already system-agnostic at the core.
`backend/app/core/evalmetrics.py:is_hit` = `document_id` match **and** `contains_evidence(text, evidence)`.
Eval items carry a verbatim evidence quote, so any system that returns its retrieved **context text** can
be scored with Hit@k / MRR / nDCG, and its answers can be judged by the existing grader. Only the
`document_id` half needs relaxing for external systems.

## Part A — Doc updates to make when this starts (PRD.md + IDEAS.md)

1. **PRD §3 Users** — make the developer persona primary for the OSS phase; Marcus/Sana become the SaaS buyers.
2. **PRD §2.1 Goals** — add G6 "Evaluate any RAG, not just ones built here" and G7 "Be a credible OSS project
   others can extend".
3. **PRD new §8.7 "Bring Your Own RAG"** (FR-4.x, below).
4. **PRD new §17 "Open source & SaaS path"**:
   - License: **Apache-2.0** (patent grant, business-friendly; keeps an open-core SaaS possible). Alternative
     AGPL if you want to block hosted clones — decide before first public tag.
   - Repo hygiene for launch: `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue/PR templates,
     GitHub Actions CI (backend pytest + frontend build), `good first issue` labels.
   - **Contribution surfaces = the registries that already exist**: node types (§10 "register a class + schema
     fragment"), vector-store adapters, LLM provider presets (`backend/app/llm/presets.py`), and new BYO adapters.
     Document each as a "how to add X" page — that's the contributor funnel.
   - Distribution: `pip install raglabs` + `raglabs serve` (one command), Docker image (PRD §9.2 trigger
     "someone else needs to run it" has now fired).
   - **Open-core line for SaaS later**: OSS keeps everything single-user/local. SaaS adds what only a hosted
     service can do: team workspaces/auth (FR-3.23), scheduled re-evals + regression alerts on a connected
     endpoint, production-query ingestion at scale (FR-3.22), hosted GPU sweeps, and the **config prior**
     (FR-3.27 — needs cross-user data, which only SaaS has). Opt-in anonymous telemetry in OSS feeds it.
5. **IDEAS.md** — new §14 entries for BYO-RAG, the CLI/CI gate, and the OSS/SaaS split; move
   "user-authored Python nodes" out of *Rejected* only for the adapter case (adapter ≠ arbitrary node).

## Part B — BYO-RAG feature design (FR-4.x)

**FR-4.1 Connection = HTTP endpoint contract** (language-agnostic; works for any stack):
```
POST <their-url>   {"question": "..."}
→ {"answer": "...", "contexts": [{"text": "...", "source": "file.pdf", "score": 0.83}]}
```
Optional field-mapping (JSONPath for `answer` / `contexts[].text` / `source`) so existing APIs work
without changes; headers for auth stored via the existing vault (`backend/app/vault.py`).
Retrieval-only endpoints (no `answer`) allowed → retrieval metrics only.

**FR-4.2 "External system" project type / version kind.** A version whose config is
`{"external": {url, mapping, headers}}` instead of a pipeline. Same Eval / Leaderboard tabs.

**FR-4.3 Corpus.** Developer uploads the same documents to RAGLabs (for eval-set generation +
Corpus Health only — no build needed), or imports their own eval set via the existing CSV import.

**FR-4.4 Scoring.** `is_hit` for external contexts: evidence match on text, with `document_id` match
replaced by filename match when `source` is given, else evidence-only. Hit@k/MRR/nDCG, latency p50/p95,
answer judging (correctness, groundedness, facets) all reuse `evaluate.py` + `evalmetrics.py`.
Diagnoses: only modes computable from outside — `not_retrieved`, and answer modes 4–7. Modes needing our
internals (`dropped_by_rerank`, `dropped_by_budget`, `ranked_below_k`) shown as "n/a for external".

**FR-4.5 Head-to-head leaderboard.** External system appears as a row next to RAGLabs configs on the same
eval set → *"Your LangChain RAG: MRR 0.52. RAGLabs best config: 0.71 (hybrid + rerank). Export it."*
That comparison is the growth loop (and the reason to then export a repo).

**FR-4.6 CLI / CI gate** (`raglabs eval --endpoint URL --set eval.csv --min-mrr 0.6`) exit non-zero on
regression → GitHub Action. This is the strongest OSS adoption feature: devs put it in CI.

**FR-4.7 Later**: Python SDK adapter (`@raglabs.system def ask(q) -> {...}`) for in-process testing; trace
ingestion (OpenTelemetry spans) so external systems get per-step latency/cost.

### Implementation sketch
- `backend/app/engine/external.py`: `async def query_external(cfg, question) -> {answer, contexts, ms}` via
  the httpx client already used by `backend/app/llm/provider.py`; map contexts to the chunk-dict shape
  `is_hit` expects.
- `evaluate.py:score_config` — branch at `score_item`: if `cfg.get("external")`, skip `ready_build` /
  rerank / pack, call `query_external`, reuse `M.first_hit_rank`, `M.summarize`, `grade_answers`.
- `evalmetrics.is_hit` — accept `document_id` **or** matching `filename`, or evidence-only when neither.
- API: version create accepts `external` config; test-connection endpoint (one sample question).
- Frontend: "Connect your RAG" option in create wizard + a small form (URL, headers, mapping, Test button).
- Tests: a fake endpoint (FastAPI TestClient) returning known contexts → assert MRR/hit values.

## Verification
- Docs: review PRD/IDEAS diffs.
- Feature: run backend pytest incl. new external-scoring test; spin up the repo-export FastAPI server
  (`POST /chat` → `{answer, sources}`, already exists) as the "external RAG", connect it, run an eval,
  confirm its metrics match the same config evaluated natively. Then UI check in a **headed** browser.

## Suggested order
1. Part A docs + OSS hygiene files (LICENSE, CONTRIBUTING, CI) — 0.5 day
2. FR-4.1–4.4 backend + test — 1.5 days
3. FR-4.5 UI + leaderboard row — 1 day
4. FR-4.6 CLI/CI gate — 0.5 day
5. Public launch (README GIF: "connect your RAG → see where it fails in 5 minutes")
