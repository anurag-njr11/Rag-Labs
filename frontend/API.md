# RAGLabs — Backend API contract (Phase 1)

Base URL: `/api` (the Vite dev server proxies `/api` → `http://127.0.0.1:8000`).
No authentication. JSON everywhere except uploads (multipart) and streams (SSE).
Errors: FastAPI shape `{"detail": string | object}`. Validation of pipeline configs returns
`422 {"detail": {"message": "Invalid configuration", "errors": PipelineFieldError[]}}`.

Times are ISO-8601 UTC strings. IDs are 32-char hex strings.

---

## Types

```ts
type Slot = 'parse' | 'chunk' | 'embed' | 'vector_store' | 'cache' | 'retrieve' | 'rerank' | 'prompt' | 'generate'
          | 'verify'   // pipeline order; `cache` is checked before retrieval
type Effect = 'rebuild' | 'instant'

/** A pipeline: every slot → { type, ...params }. Always contains all 10 slots (a config saved before `verify` or
    `cache` existed is served and validated with `{type: 'none'}` for them). */
type PipelineConfig = Record<Slot, { type: string; [param: string]: unknown }>

interface PipelineFieldError { slot: string; field: string | null; message: string }

// ---- GET /api/nodes -----------------------------------------------------
interface SlotCatalog {
  slot: Slot
  title: string            // "Vector store"
  description: string
  effect: Effect           // default effect for fields of this slot
  types: NodeType[]
}
interface NodeType {
  type: string             // "faiss"
  title: string            // "FAISS"
  description: string
  available: boolean
  unavailable_reason: string        // e.g. "Add NVIDIA_API_KEY to .env (free key: https://build.nvidia.com)"
  exact: boolean | null             // vector stores: true/false when fixed; null when config-dependent
  exact_when: Record<string, unknown[]> | null  // e.g. {"index_type": ["Flat"]} → exact iff config matches
  schema: JSONSchema                // Pydantic JSON Schema of this type's params (see "Rendering fields")
  effects: Record<string, Effect>   // param name → effect
  defaults: { type: string; [param: string]: unknown }
}
```

### Rendering fields from `schema`
`schema.properties[name]` is a JSON Schema property. Use:
- `title`, `description` → label, help text
- `type`: `integer` | `number` → slider + numeric input using `minimum`/`maximum`
  (Pydantic emits `minimum`/`maximum` from `ge`/`le`); `boolean` → toggle; `string` → text input;
  `array` of strings → tag/list editor
- `enum` (possibly via `$ref` into `schema.$defs` or `anyOf`) → select. If the property has
  `enum_labels: {value: label}`, show those labels.
- nullable strings appear as `anyOf: [{type: 'string'}, {type: 'null'}]` → text input; empty ⇒ `null`
- `widget: 'textarea'` → multiline textarea
- `advanced: true` → hide under an "Advanced" disclosure
- `options_from: "/api/providers/{provider}/models?kind=embed"` → a combobox whose options come
  from that endpoint; substitute `{field}` placeholders from the current node's values
  (`{type}` = the node type). Free text must still be allowed; empty ⇒ provider default.
- `effect` also appears inside the property when it overrides the slot default — but always use
  `NodeType.effects[name]` as the source of truth for the ⚡/🔁 badge.

```ts
// ---- projects ----------------------------------------------------------
interface IndexStatus {
  id?: string
  status: 'not_built' | 'pending' | 'building' | 'ready' | 'stale' | 'failed'
  chunk_count: number
  store: string                 // vector store type
  dim?: number | null
  error?: string | null
  stats?: BuildStats
  finished_at?: string | null
  job_id: string | null         // set while a sync job is running — subscribe to it
}
interface BuildStats {
  docs_added: number; docs_failed: number; chunks_added: number
  parse_cache_hits: number; chunk_cache_hits: number
  vectors_cached: number; vectors_embedded: number
  dim?: number; seconds: number; store_notes: string[]
}
interface Version {
  id: string; version: number; note: string; created_at: string
  index_config_hash: string; parent_id: string | null; active: boolean
  config: PipelineConfig
  index?: IndexStatus                       // included in list + detail
  changes_from_parent?: Change[]            // detail only
  parent_version?: number | null            // detail only
}
interface Project {
  id: string; name: string; description: string; created_at: string
  active_version_id: string | null
  documents: number; versions: number
  active_version: Version | null
  index: IndexStatus | null
  summary?: { vector_store: string; embed_model: string; generate: string; model: string }
}
interface Change { slot: Slot; field: string; before: unknown; after: unknown; effect: Effect }
```

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/projects` | | `Project[]` (newest first) |
| `POST /api/projects` | `{name, description?, config?}` (config omitted ⇒ recommended) | `201 Project` (v1 created & active) |
| `GET /api/projects/{id}` | | `Project` |
| `PATCH /api/projects/{id}` | `{name?, description?}` | `Project` |
| `DELETE /api/projects/{id}` | | `204` |

## Pipeline & versions

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/nodes` | | `SlotCatalog[]` in pipeline order |
| `GET /api/pipelines/recommended` | | `PipelineConfig` |
| `POST /api/pipelines/validate` | `{config}` | `{valid: true, config, index_config_hash}` or `{valid: false, errors: PipelineFieldError[]}` |
| `POST /api/projects/{id}/estimate` | `{config}` | `{changes: Change[], rebuild_needed: boolean, estimate: Estimate, index_config_hash}` |
| `GET /api/projects/{id}/versions` | | `Version[]` newest first, each with `index` |
| `GET /api/projects/{id}/versions/{vid}` | | `Version` with `index`, `changes_from_parent`, `parent_version`, `activations: {at, previous_version}[]` (newest first) |
| `GET /api/projects/{id}/versions/diff?a={vid}&b={vid}` | | `{a: number, b: number, changes: Change[]}` (a → b) |
| `POST /api/projects/{id}/versions` | `{config, note?, activate?=true, build?=true}` | `201 {version: Version, job_id: string\|null, eval_job_id: string\|null, unchanged: boolean}` — `unchanged: true` if identical to active (no new version). `eval_job_id`: regression guard — with `build: true`, the new version is scored on the newest ready eval set (null if none) |
| `GET /api/projects/{id}/suggestions` | | `{source: 'eval'\|'headings'\|'recent'\|'none', questions: string[]}` — up to 3 starter questions from the latest eval set, else section headings of the active build, else recent questions |
| `POST /api/projects/{id}/versions/{vid}/activate` | | `{version, job_id}` — also logged in `activations` |
| `POST /api/projects/{id}/versions/{vid}/build` | | `{job_id}` (409 if no documents) |
| `GET /api/projects/{id}/versions/{vid}/export` | | `application/zip` download `{slug}-v{n}-rag.zip` (409 until the version has a ready, synced build): `rag.py`, `app/main.py` (FastAPI: `POST /chat {question}` → `{answer, sources}`, `GET /health`), `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `README.md`, `.env.example`, `config.json`, `data/chunks.jsonl`, `data/vectors.npy` |
| `GET /api/projects/{id}/builds` | | `Build[]` (id, index_config_hash, config, store_type, status, dim, chunk_count, error, stats, started_at, finished_at) |

```ts
interface Estimate {
  kind: 'none' | 'reinsert' | 'reembed' | 'full'
  message: string          // show verbatim, e.g. "Vectors cached — re-inserts 1,240 chunks, no re-embedding."
  chunks?: number; documents?: number
}
```

## Documents

```ts
interface Document {
  id: string; filename: string; source_url: string | null; mime: string; size_bytes: number
  status: 'uploaded' | 'indexed' | 'failed'
  error: string | null
  parse_quality: ParseQuality | null
  created_at: string
  chunks: number | null        // in the ACTIVE index; null = not indexed there yet
  index_error: string | null   // active index couldn't process this doc
  last_modified: string | null // ISO; upload's File.lastModified or the URL's HTTP Last-Modified
  okf: DocumentOkf & {usage_count: number}  // usage_count: computed — this doc's chunks in the latest 2000 chat runs' retrieval results
}
// OKF fields (FR-2.30): from Markdown YAML front matter at upload, or PATCH below. Not index config: never rebuilds.
interface DocumentOkf {
  type?: string                 // OKF type (Guide, FAQ, Reference…), ≤80 chars; any value
  status?: string               // e.g. draft | published | deprecated (≤40 chars)
  stale_after?: string          // ISO date
  verified?: boolean | string   // true, an ISO review date, or provenance "human:…" | "process:…" | "agent:…"
                                // → trust tier human / process / agent (true or a date = human; else unverified)
  generated?: string            // ISO timestamp from the source
  sources?: string[]            // URLs or references, ≤50
}
interface ParseQuality {
  score: 'good' | 'fair' | 'poor'
  pages: number | null; chars: number; tables: number
  empty_pages: number[]; empty_page_count: number
  ocr_used: boolean; header_lines_removed: number
  warnings: string[]
}
```

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/projects/{id}/documents` | | `Document[]` |
| `POST /api/projects/{id}/documents?build=true` | multipart, field `files` repeated; optional field `last_modified` repeated, one per file in the same order (epoch ms, e.g. `File.lastModified`; `0` = unknown) | `201 {created: {id, filename}[], duplicates: {id, filename}[], errors: {filename, error}[], job_id: string\|null}` |
| `POST /api/projects/{id}/documents/url` | `{url, sitemap?: boolean, max_pages?: number, build?: boolean = true}` | `202 {job_id}` — job fetches, then builds (`build: false` = fetch only; the job's result has no `build`) |
| `POST /api/projects/{id}/documents/okf?build=true` | multipart, field `file`: an OKF bundle (.zip of Markdown with YAML front matter; ≤ 2000 files, ≤ 200 MB unpacked) | `201 {created, duplicates, skipped: {path, reason}[], errors: {path, error}[], job_id}` · 422 not a zip / too big. One document per `.md`; the bundle path is kept in the name (`guides/setup.md` → `guides__setup.md`; a single top folder is dropped); other files skipped with a reason; missing fields, unknown types and broken links are tolerated (FR-3.18) |
| `GET /api/projects/{id}/documents/okf-export` | | zip: one `.md` per document (`__` → `/`), front matter `type, title, sources, generated, status, stale_after, verified, trust, last_modified, usage_count, usage_window, x-raglabs-findings` (latest Corpus Health: contradictions, overlaps, staleness) + `index.md` (FR-3.20). Non-Markdown documents export their parsed text |
| `PATCH /api/projects/{id}/documents/{doc_id}/metadata` | `DocumentOkf` (replaces all OKF fields; omit one to clear it) | `Document` · 404 · 422 bad date |
| `DELETE /api/projects/{id}/documents/{doc_id}` | | `204` (removed from every index) |
| `POST /api/projects/{id}/documents/{doc_id}/reindex` | | `{job_id}` |
| `GET /api/projects/{id}/documents/{doc_id}/chunks?limit=200` | | `{chunks: {id, ordinal, text, token_count, is_table, page_start, page_end, heading_path}[], total}` |

Accepted file types: `.pdf .docx .md .markdown .mdx .txt .rst .html .htm`. Max 100 MB each.

## Jobs (index builds, URL fetches) — Server-Sent Events

`GET /api/jobs/{job_id}` → `{id, kind: 'sync', project_id, status: 'running'|'done'|'failed', error, result, last}`
`GET /api/projects/{id}/jobs` → running jobs for the project.

`GET /api/jobs/{job_id}/events` — SSE. Replays history, then streams live. Each message has
`event: <type>` and `data: <JSON>`:

```ts
type JobEvent =
  | { type: 'progress'; t: number; stage: 'fetch' | 'parse' | 'embed' | 'store' | 'keywords' | 'ready';
      done: number; total: number; message: string }
  | { type: 'log'; t: number; level: 'info' | 'warning' | 'error'; message: string }
  | { type: 'done'; t: number; result: { fetch?: {pages, created, duplicates, failed};
                                         build?: { id, status, chunk_count, stats: BuildStats } } }  // build absent for fetch-only jobs
  | { type: 'failed'; t: number; error: string }
```
Stage order for the progress UI: fetch (URL jobs only) → parse → embed → store → keywords → ready.
`total: 0` means indeterminate. Close the EventSource on `done`/`failed`.
Eval jobs (`kind: 'evalset' | 'eval'`, see Evaluation) report stages `index` → `generate` → `validate`
(eval set) or `index` → `evaluate` (run) on the same stream; their `done.result` is a small summary.

## Evaluation (auto-generated eval sets, retrieval scoring)

Prefix `/api/projects/{id}/eval`. Gold labels are `document_id` + a verbatim `evidence` quote, so one
set scores any version, whatever its chunking. Status is `running | ready | failed` for sets and runs.

| Method & path | Body | Returns |
|---|---|---|
| `POST /sets` | `{size?: 5–100 = 30, version_id?}` | 201 `{eval_set: EvalSet, job_id}` · 409 no documents |
| `GET /sets` | | `EvalSet[]` newest first |
| `GET /sets/{set_id}` | | `EvalSet & {items: EvalItem[]}` (rejected items included, `valid: false` + `reject_reason`) |
| `POST /sets/{set_id}/runs` | `{version_id?, answers?: false, judge?: {provider, model?}}` (default active) | 201 `{run: EvalRun, job_id}` · 409 set not ready · 422 unknown judge provider. `answers: true` also writes each answer with the version's prompt+model and LLM-grades it (extra stages `answer`, `grade`); the grader is `judge` (any provider from `GET /providers`, `model: ''` = its default), else the version's own Generate model. Judge calls use temperature 0. If no answer could be generated or graded at all, the run fails (`status: 'failed'`, `error`) rather than reporting 0% |
| `GET /runs?set_id=` | | `EvalRun[]` oldest first (no `results`) |
| `GET /runs/{run_id}` | | `EvalRun & {results: EvalItemResult[]}` |
| `GET /runs/{run_id}/fixes` | | `EvalFix[]` — one-click fixes for the run's diagnoses: `{diagnosis, config, changes: Change[], base_version}`. Save `config` via `POST /versions` |
| `POST /sets/{set_id}/items` | `{question, gold_answer, evidence, document_id, facets?: string[], tests?: string}` | 201 `EvalItem` (`valid: true`, `gold_chunk_id: ''`) · 422 evidence not found in that document's chunks / unknown document · 409 set not ready / set already has 500 valid questions |
| `PATCH /sets/{set_id}/items/{item_id}` | `{question?, gold_answer?, evidence?, facets?, tests?, valid?}` (`tests: ""` clears) | `EvalItem`. `valid: false` drops it from scoring (`reject_reason: 'removed by hand'`); `valid: true` restores it (evidence re-checked; 409 at 500 valid questions). Evidence equal to the stored value isn't re-checked |
| `DELETE /sets/{set_id}/items/{item_id}` | | 204 |
| `GET /sets/{set_id}/export.csv` | | CSV download: `question,gold_answer,evidence,document,valid,reject_reason,facets,tests` (`facets` joined with ` \| `). Cells starting with `=`, `+`, `-` or `@` get a leading `'` (spreadsheet formula guard); import strips it again |
| `POST /sets/{set_id}/import` | `{csv: string}` | `{added, skipped, error_count, errors: {row, message}[] (≤50)}` — `skipped`: rows over the 500-valid-question cap; columns `question`, `gold_answer` (or `answer`), `evidence`, `document` (file name), optional `facets` (`\|`-separated) and `tests`; rows with `valid=no` skipped; 422 missing columns |

```ts
EvalSet = {id, project_id, version_id, build_id, status, size_requested, error, created_at,
           stats: {sampled, generated, kept, too_generic, bad_evidence, other},
           revision,              // +1 on every add / edit / drop / restore / delete / imported row (FR-2.5)
           corpus_sha,            // sha256 of the sorted document content hashes at generation (null on older sets)
           corpus_changed}        // boolean: documents differ now; null when corpus_sha wasn't recorded
EvalItem = {id, ordinal, question, gold_answer, evidence, document_id, document, gold_chunk_id,
            valid, reject_reason, closed_book_answer,
            facets: string[],     // 0-4 required facts (FR-2.6); [] on older items
            tests: string | null} // Python asserts the answer's code must pass (FR-3.17); null = none
EvalRun = {id, eval_set_id, version_id, version, build_id, status, error, created_at,
           set_revision,   // the set's revision when scored (null on older runs) — compare with EvalSet.revision
           metrics: {n, k, hit_at_1, hit_at_3, hit_at_k, mrr, p50_ms,
                     ndcg_at_k?, p95_ms?,   // binary-relevance nDCG@k; 95th-percentile retrieval latency
                     context_hit?,   // share whose evidence survives the prompt's context budget
                     ctx_tokens?,    // mean context tokens sent to the model per question
                     query_tokens?,  // mean LLM tokens per question: ctx_tokens + retrieval-side calls (query
                                     // expansion, agent planning; a cached call counts what it cost). Pareto cost axis
                     cost_per_1k?: number | null,  // USD / 1,000 queries at paid-tier list price, retrieval stage
                                                   // (query expansion; 0 when off). null = a model has no known price
                     index?: {chunks, vectors, bytes},  // the scored build: chunks, vectors in the store,
                                                        // bytes of data/stores/<project>/<build>/
                     answers?: {n, ungraded, correct, partial, wrong, correct_rate,
                                correct_ci: [lo, hi] /* 95% Wilson */, grounded_rate,
                                relevant_rate?, judge?: 'provider/model',
                                context_precision?: number | null,  // mean rank-weighted contextual precision
                                context_recall?: number | null,     // mean share of facets supported by the context
                                cost_per_1k?: number | null,        // USD / 1k queries: expansion + answer generation
                                                                    // (judge calls excluded); null = unknown price
                                rejudged?: true /* sweep cells only: median of 3 judgings */,
                                answer_p50_ms?, answer_p95_ms?,     // answer time: generation + grounding checks + retries
                                verify?: {checked, errors, pass_rate: number | null, retried, mean_score: number | null}
                                         // only when the Verify slot is on (grounding check run on every answer)
                                exec_verified_rate?, exec_verified_ci?: [lo, hi],  // FR-3.17: share of questions with
                                         // tests whose code passed in the sandbox; absent when none had tests
                                execution?: {verified, unverified, ran_without_tests, missing_dependency,
                                             sandbox_unavailable, not_applicable, tested}  // status counts
                               },  // answers: true only
                     diagnoses: {incorrect_format?, incomplete_answer?, wrong_specificity?, failed_to_extract?,
                                 dropped_by_budget?, dropped_by_rerank, ranked_below_k, not_retrieved},
                     config: {parse, chunk, embed, store, retrieve, top_k, rerank}} | null}
EvalItemResult = {item_id, rank: number | null, hit,
                  diagnosis: 'incorrect_format' | 'incomplete_answer' | 'wrong_specificity' | 'failed_to_extract'
                           | 'dropped_by_budget' | 'dropped_by_rerank' | 'ranked_below_k' | 'not_retrieved' | null,
                  deep_rank, in_context?, ctx_tokens?, llm_tokens?, ms, top: {id, document, heading_path, hit}[],
                  cost_usd?: number | null,   // list-price LLM cost of this question: expansion (+ answer when graded)
                  // answers: true only
                  answer?, correct?: 'yes'|'partial'|'no', grounded?: 'yes'|'partial'|'no'|null,
                  relevant?: 'yes'|'partial'|'no'|null, specificity?: 'ok'|'too_vague'|'too_verbose'|null,
                  missing_facts?: string[],   // facets the judge found missing (items with facets)
                  answer_ms?: number,         // generation + grounding checks + retries
                  verification?: {status, grounded, score, attempt, claims},  // Verify slot on
                  execution?: {status, test_source, attempts, error, has_tests},  // code check (see Chat → Execution)
                  context_precision?: number | null,  // judge: relevant in-context passages, rank-weighted
                                                      // (mean of precision@i over relevant positions); 0 if no sources
                  context_recall?: number | null,     // judge: share of facets (else the gold answer as one)
                                                      // supported by the in-context passages; null = malformed verdict
                  format_error?: string}      // broken citation contract, e.g. "no [n] citations"
```
`dropped_by_budget` is set on a **hit** (rank ≠ null) whose chunk the prompt packer cut for
`prompt.max_context_tokens`. `failed_to_extract` (answer grading only) is a hit whose evidence was in
the prompt but whose answer was graded wrong or partial. Every failed question gets exactly one diagnosis
(FR-2.11): retrieval modes first (`not_retrieved`/`ranked_below_k`/`dropped_by_rerank` → `dropped_by_budget`), then,
for a wrong/partial answer whose evidence was in the prompt: `incorrect_format` (deterministic: no `[n]` citation,
or a number outside the sources given; only when the prompt asks for citations) → `incomplete_answer` (judge says
a required fact is missing) → `wrong_specificity` (judge: too vague / too verbose) → `failed_to_extract`.
`GET /runs/{id}/fixes` returns nothing for the four answer-level modes (no single setting fixes them).
Fields marked `?` are absent on runs scored before they existed.

### Bring your own RAG (FR-4.1–4.4)

Score a RAG that runs elsewhere with the same metrics. Header values are stored encrypted and never returned.

| Endpoint | Purpose |
|---|---|
| `GET /api/projects/{id}/external` | list systems: `{id, name, created_at, config: {url, question_field, answer_path, contexts_path, text_path, source_path, top_k, timeout_s, header_names[]}}` |
| `POST /api/projects/{id}/external` | `{name, config: {url, headers?, …mapping}}` → the system. 422 if the URL has credentials or isn't http(s) |
| `DELETE /api/projects/{id}/external/{sid}` | 204 |
| `POST /api/projects/{id}/external/test` | `{config, question?}` → `{question, ms, answer\|null, contexts[{text, external_source, score}]}`; 502 with a message if the call or mapping fails. Saves nothing |

The system is called with `POST <url> {"question": "…"}` and must return `{"answer": "…", "contexts": [{"text": "…", "source": "file.md", "score": 0.8}]}`
(paths configurable; no `answer` = retrieval only). Run it with `POST /eval/sets/{set_id}/runs` using the system's id as `version_id`; the run then has
`external: "<name>"` and `version: null`, `build_id: null`, and `metrics.config.external = <url>`. A passage is a hit when it contains the item's evidence
and, if it names a `source`, that is the item's document file. Only `not_retrieved` and answer diagnoses are produced. `answers: true` needs a `judge`.
`GET /eval/runs/{id}/fixes` returns `[]` for external runs. Questions whose call failed carry `error` and count as misses; `metrics.errors` counts them.

### Sweeps

A sweep scores every combination of a few axes (`slot.field` or `slot.type`) over a base version,
on one ready eval set — retrieval scoring; LLM calls only for `retrieve.query_expansion` cells and
`auto_optimize` answer grading. Status: `running | ready | failed | cancelled`.
Cells live inside the sweep; one becomes a real version only when promoted (`POST /versions` with
`cell.config`).

| Method & path | Body | Returns |
|---|---|---|
| `GET /sweep-axes` | | `{axes: SweepAxis[], max_cells: 48}` — suggested axes (any `slot.field` is accepted) |
| `POST /sweeps` | `{set_id, version_id?, axes: {path, values}[], auto_optimize?: false, judge?: {provider, model?}}` (1–4 axes) | 201 `{sweep: Sweep, job_id}` (job kind `sweep`) · 409 set not ready · 422 bad axis / over `max_cells` / no valid config |
| `GET /sweeps` | | `Sweep[]` newest first |
| `GET /sweeps/{sweep_id}` | | `Sweep` |
| `POST /sweeps/{sweep_id}/cancel` | | `Sweep` — stops after the current cell; finished cells stay, the rest become `skipped` |

```ts
SweepAxis = {path, label, effect: 'instant' | 'rebuild', values, requires?: {[path]: value},
             notes?: {[value]: string}, scores?: {[value]: number | null}, seed?: values}
             // embed.model: values sorted by MTEB retrieval score, `seed` = top 3
Sweep = {id, project_id, eval_set_id, base_version_id, base_version, axes: {path, values}[], status, error,
         created_at, counts: {[cellStatus]: number},
         cells: {overrides: {[path]: value}, config: PipelineConfig | null,
                 status: 'pending' | 'running' | 'ready' | 'failed' | 'invalid' | 'skipped',
                 error, metrics?: EvalRun['metrics'], build_id?, pareto?: boolean,
                 grade_error?: string /* auto_optimize: why answer grading failed; retrieval scores stand */}[]}
// A cell still `pending`/`running` when the sweep is no longer `running` (cancel, failure, restart) is returned as `skipped`.
```
`auto_optimize: true` → after all cells, the top 25% by MRR (≤5) are re-scored with answer grading
(stage `grade_cells`); their `metrics.answers` fills in, or `grade_error` is set. Then, if any graded cell's 95%
interval overlaps the leader's (best `correct_rate`), the leader and those cells are judged twice more (stage
`rejudge`) and keep each question's median verdict; their `metrics.answers.rejudged = true` (FR-2.8). `pareto` = on the frontier of MRR (higher) vs. `query_tokens` (lower; `ctx_tokens` on older sweeps). Cells tied with a
picked one on MRR and tokens are graded too (≤5): they differ only in answer-side settings. The `verify.type` axis carries
`answers_only: true` — only Auto-Optimize's answer grading tells its cells apart. Varying `chunk.size` without
`chunk.overlap` keeps the base overlap/size ratio. `invalid` cells carry the validation message.

### Embedding adapters (FR-3.10/3.12)

| Method & path | Body / returns |
|---|---|
| `POST /eval/adapters` | `{set_id, version_id?}` → 201 `{adapter: Adapter, job_id}` (409 set not ready). Stages `index` → `embed` → `train` |
| `GET /eval/adapters` | `Adapter[]`, newest first |
| `GET /eval/adapters/{id}` | `Adapter` |
| `DELETE /eval/adapters/{id}` | 204; versions that name it skip it from then on |

```ts
Adapter = {id, version_id, version, eval_set_id, status: 'running'|'ready'|'failed', error, created_at, embed_key, dim,
  metrics: {questions, train, chunks, dim, generalises /* holdout MRR improved */,
            cv_passed /* some λ beat the plain embedder by > 0.02 MRR in ≥ 2 of 3 folds */,
            recommended /* cv_passed && generalises — only then does the UI offer it */,
            params /* {tau, lambda (chosen), steps, lr} */, cv /* {identity, '0.01', …: mean fold MRR} */,
            holdout: {before: RankScores, after: RankScores},   // 25% of questions it never saw
            full: {before: RankScores, after: RankScores}} | null}   // in-sample, the saved (refitted) adapter
RankScores = {recall_at_k /* k = 5 */, mrr, n}   // dense-only brute-force ranking of every chunk
```
A query-side linear map (q' = W q, kept at q's length), stored at `data/adapters/<project>/<id>.npy`. Use it by setting
`retrieve.adapter` to its id (instant). It applies only when it's ready and was trained for the version's embedder
(`embed_key`); otherwise retrieval skips it and `embed_query`'s payload says `adapter: "skipped: …"` (else `adapter: <id>`).
Repo export ships it as `data/adapter.npy`. Training needs ≥ 8 questions whose evidence is in the index; with fewer the job fails with that message.

### Prompt optimisation (FR-3.11)

| Method & path | Body / returns |
|---|---|
| `POST /eval/prompt-runs` | `{set_id, version_id?}` → 201 `{run: PromptRun, job_id}` (409 set not ready). Stages `index` → `retrieve` → `bootstrap` → `propose` → `select` → `test` |
| `GET /eval/prompt-runs` | `PromptRun[]`, newest first |
| `GET /eval/prompt-runs/{id}` | `PromptRun` |

```ts
PromptRun = {id, version_id, version, eval_set_id, status, error, created_at,
  result: {splits: {train, val, test},          // deterministic by item id: 40 / 30 / 30 %
           candidates: {extra_instructions, examples, val_score, answered, is_current}[],
           best: {extra_instructions, examples, is_current},
           test: {before, after, n},             // mean score on test questions never used to choose
           improves, demos,
           samples: {question, gold, before, before_score, after, after_score}[]} | null}
```
Score per answer: token F1 against the gold answer (citation markers stripped), halved when the answer breaks the
citation contract. Candidates = {current, each proposed instruction block} × {no examples, bootstrapped examples}
(+ the current prompt as-is). Use the winner by saving a version with `prompt.extra_instructions` / `prompt.examples`
(appended to the system prompt, also in repo export). Needs ≥ 9 questions. The Verify slot is left out while optimising.

### Injection resistance (FR-3.7/3.8)

| Method & path | Body / returns |
|---|---|
| `POST /eval/injection` | `{set_id, version_id?, questions?: 1–20 (5), compare?: true}` → 201 `{run: InjectionRun, job_id}` (409 set not ready) |
| `GET /eval/injection` | `InjectionRun[]`, newest first (no `results`) |
| `GET /eval/injection/{id}` | `InjectionRun & {results}` |

```ts
InjectionRun = {id, version_id, version, eval_set_id, status: 'running'|'ready'|'failed', error, created_at,
  options: {questions, compare},
  metrics: {questions, failed_trials, payloads: {id, label, goal}[],
            variants: {id: 'current'|'none'|'data_rule'|'delimited'|'source_labels'|'output_validation'|'grounding_check'|'all',
                       label, defences: string[], trials, hijacked, caught_by_check, caught_by_filter, resisted,
                       score /* 1 − hijacked/trials */, by_payload: {[payload]: {trials, hijacked}}}[]} | null,
  results?: {variant, payload, outcome: 'hijacked'|'caught_by_check'|'caught_by_filter'|'resisted',
             answer /* first 400 chars, after output validation */, removed: string[], question, item_id}[]}
```
Job stages `index` → `retrieve` → `attack`. Each trial retrieves the question as usual, puts a poisoned passage at rank 1
(in memory — the corpus is never changed), answers with the variant's prompt / generate / verify settings, and checks
for the payload's canary (`prompt_leak`: 8 consecutive words of the system prompt). Payloads: `override`,
`exfiltration`, `contact_swap`, `false_fact`, `prompt_leak`. Variants (`compare`): as configured, no defences, each
defence alone, all. A failed grounding check counts as caught (retries aren't simulated).

## Chat-to-build (FR-3.25)

`POST /api/projects/{id}/build-chat` `{instruction (2–1000 chars), config? /* the draft; default the active version */}` →
`{config /* validated draft */, changes: Change[] /* vs the input */, explanation, attempts, rebuild?, error?}` · 502
provider error · 422 invalid input config. The draft's Generate model (temperature 0) sees a compact catalog of slots,
types and fields (types, enums, min/max, defaults) and answers with `{changes: [{path: "slot.field"|"slot.type", value}]}`;
the server applies them (types first; a type change resets the slot to that type's defaults, keeping shared fields),
validates, and gives the model one repair round with the error. `changes: []` with `explanation` (or `error`) = nothing
proposed. Nothing is saved.

## Recipes (FR-3.26) and the config prior (FR-3.27)

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/recipes` | | `Recipe[]` — saved (newest first), then built-in. `Recipe = {id, name, description, tags, builtin, config, created_at, source_project?}` |
| `POST /api/recipes` | `{name, description?, tags?, config, source_project?}` | 201 `Recipe` (validated; `retrieve.adapter` cleared) · 422 |
| `DELETE /api/recipes/{rid}` | | 204 · 404 · 409 built-in |
| `POST /api/projects/{id}/recipe-config` | `{config}` | `{config, notes: string[]}` — made fit for this project: adapter dropped, an unconnected Generate provider replaced by the project's own. Save it with `POST /versions` |
| `GET /api/projects/{id}/config-prior` | | `{source: 'prior'\|'rules', history, fingerprint, suggestions: {path, value, confidence: number\|null, votes?, sweeps?, mean_similarity?, reason?, current?, skipped?}[], config, verify_axes: {path, values}[]}` |

Sharing is client-side: `/recipes#recipe=<base64url JSON {name, description, tags, config}>`; the Recipes page offers
to import it. Prior: fingerprints of logged sweeps (`sweep_fingerprints`) with similarity ≥ 0.6 vote for their
winning overrides; `confidence = vote share × (1 − e^(−n/3)) × mean similarity`. No history → `source: 'rules'` (the
rule-based recommender, `confidence: null`). `verify_axes` = each predicted change vs the current value (≤ 4).

## API keys & usage (FR-3.23)

Requests from loopback (the web UI on this machine) need no key while `TRUST_LOOPBACK=true` (default). Any other
request to `/api/*` (except `/api/health`) needs `Authorization: Bearer rl_…` → 401 without one (`WWW-Authenticate:
Bearer`), 401 for an invalid or revoked key (even from loopback), 403 when a `chat` key calls anything but
`POST /api/projects/{its project}/chat`. A keyed call is recorded as `source: api` with `api_key_id`.

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/keys` | | `{id, name, scope: 'chat'\|'admin', project_id, prefix, created_at, last_used_at, revoked_at}[]` (never the key) |
| `POST /api/keys` | `{name, scope?: 'chat', project_id? /* required for chat */}` | 201 the same + `key` — the only time it is returned; only its SHA-256 is stored |
| `DELETE /api/keys/{kid}` | | 204 revoked · 404 |
| `GET /api/projects/{id}/usage?days=30` | | `{days, daily: {day, requests, errors, tokens_in, tokens_out, cost_usd, api}[], total: {…, playground}, latency: {p50_ms, p95_ms}, by_key: {id, name, prefix, requests}[]}` |

Team workspaces / multi-tenancy are not in the self-hosted edition.

## Data tables & attested computations (FR-3.21)

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/projects/{id}/data` | | `{table, columns: {name, type}[], rows}[]` |
| `POST /api/projects/{id}/data` | multipart `files` (CSV/TSV, ≤ 50 MB, ≤ 200k rows) | `201 {created: DataTable[], errors: {filename, error}[]}` — a file replaces the same-named table; types inferred (INTEGER/REAL/TEXT, "1,250" → 1250) |
| `DELETE /api/projects/{id}/data/{table}` | | 204 · 404 |
| `GET /api/projects/{id}/computations` | | `Computation[]` |
| `POST /api/projects/{id}/computations` | `ComputationSpec` | 201 `Computation` · 422 (not a single SELECT, undeclared `:param`, SQL error against the data, no data yet) |
| `PUT /api/projects/{id}/computations/{cid}` | `ComputationSpec` | `Computation` |
| `DELETE /api/projects/{id}/computations/{cid}` | | 204 |
| `POST /api/projects/{id}/computations/{cid}/run` | `{parameters}` | `ComputeReceipt` · 422 bad values / SQL error |

```ts
ComputationSpec = {name, description /* the router reads it */, unit,
  sql,                                   // one SELECT / WITH…SELECT, params as :name
  parameters: {name, type: 'integer'|'number'|'string'|'date', required, description, options: string[]|null}[],
  attester: {min_rows, max_rows, columns: string[] /* expected, in order */, non_null,
             bounds: {[column]: [min|null, max|null]}}}
ComputeReceipt = {name, computation_id?, parameters, sql, attested, answer: string|null /* rendered from the result */,
  result: {columns, rows, truncated, ms} | null, checks: {check, ok, detail}[], error?}
```
With `compute.type = attested` (slot before retrieve; `on_fail: documents | refuse`), chat first asks the Generate model to
pick a computation and fill its parameters (`compute_route` trace step; it never writes SQL). The values are type-checked,
the query runs on a read-only connection (`mode=ro`, `query_only`, 2 s limit, ≤ 200 rows), and every attestation check must
pass (`compute` step). Attested → the answer is `receipt.answer`, no retrieval or generation; `done.computation` carries the
receipt. Not attested → documents answer as usual (`done.computation.attested = false`) or, with `refuse`, a refusal.
Questions routed to a computation are never cached. Not in repo export. Departure from OKF v0.2: attesters are
declarative checks, not Python files — running uploaded code would be arbitrary code execution.

## Corpus Health

Prefix `/api/projects/{id}/health`. A report analyses one version's build: real questions
(Playground/API history + pasted) → coverage verdicts and a gap backlog; cross-document passage
pairs → duplicates and contradictions; and which chunks/documents those questions ever retrieved.
Every chat run records `source`: `playground` when the request carries `X-RAGLabs-Client: playground` (the
Playground sends it), else `api`. With the monitor on, a report starts on its own (`trigger: 'auto'`) after
`every_n` new OK chat runs from `sources` since the latest report — checked after each answer. Reports carry
`trigger` (`manual | auto`), `sources`, and `result.trend` vs the previous ready report: `{previous_covered_rate,
covered_rate_change, resolved, regressed, new_gaps, new_questions}` (null for the first; per-question
`coverage.outcomes` maps normalised question → covered | gap | retrieval_miss).
Status `running | ready | failed`. Job kind `health`, progress stages `index?` → `retrieve` →
`judge` → `recheck` → `scan` → `contradictions`. `recheck` re-judges each gap against the top 15 of a
deep retrieval (one call per 5 gaps): answered → a retrieval miss, not a content gap. Staleness uses
documents' OKF `status`/`stale_after` and `last_modified` (see Documents).

| Method & path | Body | Returns |
|---|---|---|
| `POST /reports` | `{version_id?, questions?: string[] (≤500), stale_days?: number (1–36500, default 365), sources?: 'all' \| 'api'}` | 201 `{report: HealthReport, job_id}` · 409 no documents. `sources: 'api'` uses only API history (production), not Playground |
| `GET /monitor` | | `{settings: {enabled, every_n (5–10000), sources: 'all'\|'api', stale_days}, since_last_report: {last_report_at, api, playground, all}}` — FR-3.22 |
| `PUT /monitor` | `settings` | the same + `job_id` (a report started at once if already past the threshold) |
| `GET /reports` | | `HealthReport[]` newest first, with `summary` (no `result`) |
| `GET /reports/{rid}` | | `HealthReport` with `result` |
| `GET /reports/{rid}/report.md` | | Markdown download (`Content-Disposition: attachment`) · 409 not ready |

```ts
HealthReport = {id, project_id, version_id, version, build_id, status, error, created_at,
                result?: HealthResult | null,
                summary?: {n, covered, partial, missing, covered_rate, ungraded, retrieval_miss?, sources,
                           topics, contradictions, duplicates, unused_documents, stale_documents} | null}
Excerpt = {chunk_id, document_id, document, heading_path, page_start, text /* ≤600 chars */}
HealthResult = {
  coverage: {summary: {n, covered, partial, missing, covered_rate, ungraded, retrieval_miss, sources: {pasted, history}},
             topics: {topic, count, missing, partial,      // content gaps only, biggest first
                      questions: {question, verdict: 'covered'|'partial'|'missing', source: 'pasted'|'history',
                                  passages: Excerpt[] /* closest one */}[]}[],
             retrieval_misses: {question, verdict: 'partial'|'missing', source}[]}  // deep top 15 answers it
  duplicates: {a: Excerpt, b: Excerpt, similarity}[]           // cosine ≥ 0.97, different documents
  contradictions: {a, b, similarity, explanation}[]              // LLM-confirmed among the 30 closest pairs
  pairs_checked: number
  usage: {questions, chunks, chunks_used, unused_documents,
          documents: {document_id, document, chunks, used}[]}  // least used first
  staleness: {max_age_days, documents_checked, with_dates /* docs with last_modified or stale_after */,
              documents: {document_id, document, reasons: ('deprecated'|'past_stale_after'|'old')[],
                          status, stale_after, last_modified, age_days: number|null}[]}  // oldest first
}
// Reports made before 2026-10-06 lack `retrieval_misses`, `summary.retrieval_miss` and `staleness`.
```

## Chat

`POST /api/projects/{id}/chat` body `{question, version_id?, stream?: true}`.
`version_id` omitted ⇒ active version. If the index isn't up to date the server builds it first
(emitting a `status` event). Response with `stream: true` is SSE — **use `fetch` + a stream reader
(POST), not `EventSource`**. Parse `event:`/`data:` lines; messages are separated by a blank line.

```ts
type ChatEvent =
  | { type: 'status'; message: string; job_id: string }       // index being updated first
  | { type: 'run'; run_id: string; version: number; build_id: string; store: string }
  | { type: 'retrieval'; results: RetrievedChunk[]; trace: TraceStep[] }  // before any tokens
  | { type: 'token'; text: string }                           // append to the answer
  // verify.type = grounding_check only:
  | { type: 'verifying' }                                     // the answer is being checked against its sources
  | { type: 'verify'; verification: Verification }            // result of that check (one per attempt)
  | { type: 'retry'; attempt: number; reason: string }         // not grounded: clear the answer; retrieval → tokens
                                                              // → verify repeat with twice top_k/top_n/context budget
  // verify.type = execution_check only: { type: 'verifying'; what: 'code' } first, then
  | { type: 'execution'; execution: Execution }               // after the tokens; a fixed answer may differ from
                                                              // them — show `done.answer`, the final text
  | { type: 'done'; run_id: string; answer: string; citations: Citation[];
      retrieved: RetrievedChunk[]; trace: TraceStep[];
      totals: { ms: number; tokens_in: number; tokens_out: number; cost_usd: number; latency_ms: number };
                                      // cost_usd excludes unpriced steps — check trace payload.priced
      truncated: boolean                                      // true if max tokens cut the answer
      verification: Verification | null                       // null when verify.type = none
      execution: Execution | null                             // code check result; null unless execution_check
      cache: {question, similarity, created_at, run_id} | null }  // answered from the semantic cache: the earlier
                                                              // question matched; then the only trace step is
                                                              // cache_lookup — no retrieval, no LLM call
  | { type: 'error'; code: string; message: string }          // show message verbatim

interface RetrievedChunk {
  id: string; document_id: string; document: string; source_url: string | null
  ordinal: number; text: string; token_count: number; is_table: boolean
  page_start: number | null; page_end: number | null; heading_path: string
  rank: number                 // final rank (after rerank if on)
  retrieval_rank: number       // rank before rerank
  score: number                // fused score
  scores: Partial<Record<'dense' | 'keyword' | 'exact' | 'rerank', number>>
  ranks: Partial<Record<'dense' | 'keyword' | 'exact', number>>
  found_by: ('dense' | 'keyword' | 'exact')[]
  exact_keys: string[]         // which normalised error/symbol keys matched; "heading:<id>" = the
                               // chunk's section heading names it (a defining section)
  pinned: boolean              // moved to the top because it is a defining section (retrieve.pin_definitions)
  in_context: boolean          // made it into the prompt (false = dropped for the token budget)
  context_n: number | null     // its [n] number in the prompt
  cited?: boolean              // present on `done`
  window?: number[]            // retrieve.context_window > 0: ordinals in `window_text` (this chunk ± neighbours,
                               // same document)
  window_text?: string         // what the prompt got for this hit (neighbours merged); `text`/`token_count` stay the
                               // hit's own, which rerank, eval hit checks and judges use
}
interface Citation {
  n: number                    // matches [n] in the answer text
  chunk_id: string; document_id: string; document: string
  page_start: number | null; page_end: number | null; heading_path: string
  spans: [number, number][]    // char ranges in the chunk text to highlight
  support?: 'yes' | 'partial' | 'no' | null  // grounding check: does this source support the claims citing it
}
interface Verification {       // FR-3.5 grounding check + FR-3.9 citation support, one LLM call (Generate's model, temp 0)
  status: 'ok' | 'error'       // error = the check call failed or returned no JSON: grounded/score null, no retry
  grounded: boolean | null     // true unless some claim is 'no' ('partial' passes); no claims ("I don't know") = true
  score: number | null         // mean claim support: yes 1, partial 0.5, no 0
  claims: { claim: string; supported: 'yes' | 'partial' | 'no'; cited: Record<string, 'yes' | 'partial' | 'no'> }[]
  citations: Record<string, 'yes' | 'partial' | 'no'>  // source n → worst verdict across claims citing it
  attempt: number              // 0 = first answer; n = after n retries
  error?: string
}
interface TraceStep {
  seq: number
  step: 'embed_query' | 'dense_search' | 'keyword_search' | 'exact_search' | 'fuse' | 'pin' | 'mmr'
      | 'rerank' | 'prompt' | 'generate' | 'query_expansion' | 'context_window' | 'verify'
  ms: number
  start_ms?: number | null      // offset from the run's start (concurrent steps overlap); null on older runs; tokens_in: number; tokens_out: number
  cost_usd: number                  // paid-tier list price of the step's LLM call (free tiers cost $0)
  payload: Record<string, unknown>  // e.g. {hits: 12, store: 'faiss', exact: true} / {included: 5, dropped: 2}
                                    // priced: false → the model has no known price: cost_usd is 0, show "—"
                                    // query_expansion cached: true → uncached_cost_usd (number|null): what the call cost
                                    // query_expansion (retrieve.query_expansion ≠ none; carries the LLM tokens):
                                    //   {mode, provider, model, queries: string[], passage: string|null,
                                    //    fallback: bool, error?, cached?}; with multi_query / decompose,
                                    //   dense_search / keyword_search repeat per rewrite / sub-question with
                                    //   {query: 1..n}. decompose: fuse payload {method: 'decompose+rrf'|…, groups}
                                    //   — each (sub-)question fused on its own, then interleaved into the top-k
                                    // context_window: {window, chunks_added}
                                    // okf_policy (retrieve.okf_policy): {dropped /* past stale_after */,
                                    //   demoted /* deprecated: score × 0.5 */}; equal scores → human > process >
                                    //   agent > unverified verified sources (FR-3.19). Ported to repo export
                                    // agent (retrieve.type = agentic; one per planner LLM call, carries its tokens):
                                    //   {turn, action: 'search'|'read'|'done'|'error', queries?, read?, keep?,
                                    //    invalid_reply?, context_chars, offload, provider, model}; the agent's
                                    //   searches appear as ordinary embed_query / dense_search / … steps.
                                    //   A cached run (same question + config, any top_k): {cached: true, steps,
                                    //   uncached_cost_usd, uncached_tokens}. query_expansion's cached payload also
                                    //   carries uncached_tokens
                                    // generate: {provider, model, first_token_ms, finish_reason,
                                    //            reasoning_tokens (number|null), reasoning_effort}
                                    // verify: {status, grounded, score, claims, unsupported}; a retry repeats the
                                    //   retrieval steps, prompt, generate and verify
                                    // output_validation (verify.validate_output): {removed, items: string[]} — the
                                    //   answer is then sent as ONE token event after generation (not streamed)
                                    // cache_lookup (cache.type = semantic; first step): {hit, similarity|null,
                                    //   threshold, entries, guard_blocked?} — guard_blocked: similar enough, but
                                    //   the numbers / code identifiers in the two questions differ
}
```
Citation markers in the answer look like `[1]`, `[2][3]` or `[1, 2]`; `n` indexes `context_n`.

```ts
// Code check (verify.type = execution_check, FR-3.13–3.16). Runs only in Docker (SANDBOX_IMAGE).
interface Execution {
  status: 'verified'            // tests passed (test_source says which tests)
        | 'unverified'          // still failing after max_steps / the same error twice: best attempt shown
        | 'ran_without_tests'   // ran cleanly, but there were no tests
        | 'missing_dependency'  // the sandbox image lacks an imported package (error says which)
        | 'sandbox_unavailable' // Docker not installed / not running (error says which); nothing was run
        | 'not_applicable'      // no ```python block in the answer
  test_source?: 'provided' | 'doctest' | 'generated' | 'none'  // generated = weaker evidence
  tests?: string; attempts?: number; error?: string
  steps: {step, ok, stage /* answer | tests | sandbox */, tests_run, detail /* traceback, ≤1500 chars */, ms}[]
}
```
An unverified answer isn't stored in the semantic cache.

With `stream: false` the response is JSON:
`{answer, citations, sources: {rank, document, page_start, page_end, heading_path, found_by, scores, cited, text}[], run_id, totals, verification}`
(errors: 409 no documents / build failed, 502 provider error, `detail: {code, message}`).

| Method & path | Returns |
|---|---|
| `GET /api/projects/{id}/runs?limit=50` | `{id, version_id, question, status ('running'\|'ok'\|'error'\|'aborted'), latency_ms, tokens_in, tokens_out, cost_usd, created_at}[]` |
| `GET /api/runs/{run_id}` | full run incl. `result` (retrieved, citations, messages, verification, cache) and `events: TraceStep[]` |
| `GET /api/projects/{id}/cache` | semantic answer cache `{entries, hits}` (all configurations) |
| `DELETE /api/projects/{id}/cache` | empty it → `{cleared}` |

Semantic cache scope: a hit needs the same project, the same config (every slot but `cache`) and the same documents
(content hashes), cosine ≥ `threshold` with the project's embedder, and identical numbers / code identifiers. Only
finished answers are cached — not truncated ones, and not ones the grounding check failed. Eval runs never use it.

## Providers & health

| Method & path | Returns |
|---|---|
Providers back the **Generate** slot: each enabled provider is a Generate node type named after
it (so the catalog in `GET /api/nodes` changes when providers are added or removed — refetch it).
The Embed slot's `api` type still only accepts `gemini` / `nvidia`.

| Method & path | Returns |
|---|---|
| `GET /api/health` | `{status: 'ok', providers: {[name]: boolean}}` |
| `GET /api/providers` | `Provider[]` — the enabled providers (Gemini, NVIDIA + every configured one) |
| `GET /api/providers/presets` | `Provider[]` — every built-in preset with its current state |
| `POST /api/providers` | create a custom endpoint (or connect a preset): `ProviderInput` with `name` → `Provider` (201; 409 if it exists, 422 invalid) |
| `PATCH /api/providers/{name}` | update: `ProviderInput` (omitted fields kept; empty `api_key` keeps the stored key) → `Provider` |
| `DELETE /api/providers/{name}` | forget UI settings (a preset falls back to `.env`; a custom one disappears) → 204 |
| `POST /api/providers/{name}/test` | `{ok, error?, models?, sample?, ms}` — calls the endpoint's `/models` |
| `POST /api/providers/test` | same, for unsaved settings (`ProviderInput`; missing fields fall back to `name`'s) |
| `GET /api/providers/{name}/models?kind=chat\|embed` | `{models: string[]}` (default first) |

`Provider`: `{name, title, description, base_url, default_model, signup_url, key_required,
supports_reasoning, headers: string[] (names only), source: 'preset'|'env'|'ui'|'custom-env'|'custom-ui',
preset: string|null, custom, key_set, key_hint ('…abcd'), key_env, available, reason, enabled}`.
The API key and header values are never returned (they're encrypted at rest); credentials in
`base_url` are masked. Saving refuses a `base_url` that contains credentials, and refuses a
`base_url` change unless `api_key` (and `headers`, if any were set) are sent again (422).

`ProviderInput`: `{name?, title?, base_url?, api_key?, default_model?, supports_reasoning?,
key_required?, headers?: {[name]: value}}`.

If no provider is available, show a banner linking to the LLM providers page
(`/settings/providers`); chat will fail with an `error` event until then.
