# RAGLabs — Backend API contract (Phase 1)

Base URL: `/api` (the Vite dev server proxies `/api` → `http://127.0.0.1:8000`).
No authentication. JSON everywhere except uploads (multipart) and streams (SSE).
Errors: FastAPI shape `{"detail": string | object}`. Validation of pipeline configs returns
`422 {"detail": {"message": "Invalid configuration", "errors": PipelineFieldError[]}}`.

Times are ISO-8601 UTC strings. IDs are 32-char hex strings.

---

## Types

```ts
type Slot = 'parse' | 'chunk' | 'embed' | 'vector_store' | 'retrieve' | 'rerank' | 'prompt' | 'generate'
type Effect = 'rebuild' | 'instant'

/** A pipeline: every slot → { type, ...params }. Always contains all 8 slots. */
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
  okf: DocumentOkf & {usage_count: number}  // usage_count: computed — this doc's chunks in recorded runs' retrieval results
}
// OKF fields (FR-2.30): from Markdown YAML front matter at upload, or PATCH below. Not index config: never rebuilds.
interface DocumentOkf {
  status?: string               // e.g. draft | published | deprecated (≤40 chars)
  stale_after?: string          // ISO date
  verified?: boolean | string   // true or an ISO date
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
| `POST /sets/{set_id}/runs` | `{version_id?, answers?: false, judge?: {provider, model?}}` (default active) | 201 `{run: EvalRun, job_id}` · 409 set not ready · 422 unknown judge provider. `answers: true` also writes each answer with the version's prompt+model and LLM-grades it (extra stages `answer`, `grade`); the grader is `judge` (any provider from `GET /providers`, `model: ''` = its default), else the version's own Generate model. Judge calls use temperature 0 |
| `GET /runs?set_id=` | | `EvalRun[]` oldest first (no `results`) |
| `GET /runs/{run_id}` | | `EvalRun & {results: EvalItemResult[]}` |
| `GET /runs/{run_id}/fixes` | | `EvalFix[]` — one-click fixes for the run's diagnoses: `{diagnosis, config, changes: Change[], base_version}`. Save `config` via `POST /versions` |
| `POST /sets/{set_id}/items` | `{question, gold_answer, evidence, document_id, facets?: string[]}` | 201 `EvalItem` (`valid: true`, `gold_chunk_id: ''`) · 422 evidence not found in that document's chunks / unknown document · 409 set not ready |
| `PATCH /sets/{set_id}/items/{item_id}` | `{question?, gold_answer?, evidence?, facets?, valid?}` | `EvalItem`. `valid: false` drops it from scoring (`reject_reason: 'removed by hand'`); `valid: true` restores it (evidence re-checked) |
| `DELETE /sets/{set_id}/items/{item_id}` | | 204 |
| `GET /sets/{set_id}/export.csv` | | CSV download: `question,gold_answer,evidence,document,valid,reject_reason,facets` (`facets` joined with ` \| `) |
| `POST /sets/{set_id}/import` | `{csv: string}` | `{added, error_count, errors: {row, message}[] (≤50)}` — columns `question`, `gold_answer` (or `answer`), `evidence`, `document` (file name), optional `facets` (`\|`-separated); rows with `valid=no` skipped; 422 missing columns |

```ts
EvalSet = {id, project_id, version_id, build_id, status, size_requested, error, created_at,
           stats: {sampled, generated, kept, too_generic, bad_evidence, other},
           revision,              // +1 on every add / edit / drop / restore / delete / imported row (FR-2.5)
           corpus_sha,            // sha256 of the sorted document content hashes at generation (null on older sets)
           corpus_changed}        // boolean: documents differ now; null when corpus_sha wasn't recorded
EvalItem = {id, ordinal, question, gold_answer, evidence, document_id, document, gold_chunk_id,
            valid, reject_reason, closed_book_answer,
            facets: string[]}     // 0-4 required facts (FR-2.6); [] on older items
EvalRun = {id, eval_set_id, version_id, version, build_id, status, error, created_at,
           set_revision,   // the set's revision when scored (null on older runs) — compare with EvalSet.revision
           metrics: {n, k, hit_at_1, hit_at_3, hit_at_k, mrr, p50_ms,
                     ndcg_at_k?, p95_ms?,   // binary-relevance nDCG@k; 95th-percentile retrieval latency
                     context_hit?,   // share whose evidence survives the prompt's context budget
                     ctx_tokens?,    // mean context tokens sent to the model per question
                     answers?: {n, ungraded, correct, partial, wrong, correct_rate,
                                correct_ci: [lo, hi] /* 95% Wilson */, grounded_rate,
                                relevant_rate?, judge?: 'provider/model',
                                rejudged?: true /* sweep cells only: median of 3 judgings */},  // answers: true only
                     diagnoses: {incorrect_format?, incomplete_answer?, wrong_specificity?, failed_to_extract?,
                                 dropped_by_budget?, dropped_by_rerank, ranked_below_k, not_retrieved},
                     config: {parse, chunk, embed, store, retrieve, top_k, rerank}} | null}
EvalItemResult = {item_id, rank: number | null, hit,
                  diagnosis: 'incorrect_format' | 'incomplete_answer' | 'wrong_specificity' | 'failed_to_extract'
                           | 'dropped_by_budget' | 'dropped_by_rerank' | 'ranked_below_k' | 'not_retrieved' | null,
                  deep_rank, in_context?, ctx_tokens?, ms, top: {id, document, heading_path, hit}[],
                  // answers: true only
                  answer?, correct?: 'yes'|'partial'|'no', grounded?: 'yes'|'partial'|'no'|null,
                  relevant?: 'yes'|'partial'|'no'|null, specificity?: 'ok'|'too_vague'|'too_verbose'|null,
                  missing_facts?: string[],   // facets the judge found missing (items with facets)
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

### Sweeps

A sweep scores every combination of a few axes (`slot.field` or `slot.type`) over a base version,
on one ready eval set — retrieval only, no LLM calls. Status: `running | ready | failed | cancelled`.
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
                 error, metrics?: EvalRun['metrics'], build_id?, pareto?: boolean}[]}
```
`auto_optimize: true` → after all cells, the top 25% by MRR (≤5) are re-scored with answer grading
(stage `grade_cells`); their `metrics.answers` fills in, or `grade_error` is set. Then, if any graded cell's 95%
interval overlaps the leader's (best `correct_rate`), the leader and those cells are judged twice more (stage
`rejudge`) and keep each question's median verdict; their `metrics.answers.rejudged = true` (FR-2.8). `pareto` = on the frontier of MRR (higher) vs. `ctx_tokens` (lower). Varying `chunk.size` without
`chunk.overlap` keeps the base overlap/size ratio. `invalid` cells carry the validation message.

## Corpus Health

Prefix `/api/projects/{id}/health`. A report analyses one version's build: real questions
(Playground/API history + pasted) → coverage verdicts and a gap backlog; cross-document passage
pairs → duplicates and contradictions; and which chunks/documents those questions ever retrieved.
Status `running | ready | failed`. Job kind `health`, progress stages `index?` → `retrieve` →
`judge` → `recheck` → `scan` → `contradictions`. `recheck` re-judges each gap against the top 15 of a
deep retrieval (one call per 5 gaps): answered → a retrieval miss, not a content gap. Staleness uses
documents' OKF `status`/`stale_after` and `last_modified` (see Documents).

| Method & path | Body | Returns |
|---|---|---|
| `POST /reports` | `{version_id?, questions?: string[] (≤500), stale_days?: number (1–36500, default 365)}` | 201 `{report: HealthReport, job_id}` · 409 no documents |
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
  | { type: 'done'; run_id: string; answer: string; citations: Citation[];
      retrieved: RetrievedChunk[]; trace: TraceStep[];
      totals: { ms: number; tokens_in: number; tokens_out: number; cost_usd: number; latency_ms: number };
      truncated: boolean }                                    // true if max tokens cut the answer
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
  window?: number[]            // retrieve.context_window > 0: ordinals merged into `text` (this chunk ± neighbours,
                               // same document); `token_count` covers the merged text, `id`/`ordinal` stay the hit's
}
interface Citation {
  n: number                    // matches [n] in the answer text
  chunk_id: string; document_id: string; document: string
  page_start: number | null; page_end: number | null; heading_path: string
  spans: [number, number][]    // char ranges in the chunk text to highlight
}
interface TraceStep {
  seq: number
  step: 'embed_query' | 'dense_search' | 'keyword_search' | 'exact_search' | 'fuse' | 'pin' | 'mmr'
      | 'rerank' | 'prompt' | 'generate' | 'query_expansion' | 'context_window'
  ms: number; tokens_in: number; tokens_out: number; cost_usd: number
  payload: Record<string, unknown>  // e.g. {hits: 12, store: 'faiss', exact: true} / {included: 5, dropped: 2}
                                    // query_expansion (retrieve.query_expansion ≠ none; carries the LLM tokens):
                                    //   {mode, provider, model, queries: string[], passage: string|null,
                                    //    fallback: bool, error?, cached?}; with multi_query, dense_search /
                                    //   keyword_search repeat per rewrite with {query: 1..n}
                                    // context_window: {window, chunks_added}
                                    // generate: {provider, model, first_token_ms, finish_reason,
                                    //            reasoning_tokens (number|null), reasoning_effort}
}
```
Citation markers in the answer look like `[1]`, `[2][3]` or `[1, 2]`; `n` indexes `context_n`.

With `stream: false` the response is JSON:
`{answer, citations, sources: {rank, document, page_start, page_end, heading_path, found_by, scores, cited, text}[], run_id, totals}`
(errors: 409 no documents / build failed, 502 provider error, `detail: {code, message}`).

| Method & path | Returns |
|---|---|
| `GET /api/projects/{id}/runs?limit=50` | `{id, version_id, question, status ('running'\|'ok'\|'error'\|'aborted'), latency_ms, tokens_in, tokens_out, cost_usd, created_at}[]` |
| `GET /api/runs/{run_id}` | full run incl. `result` (retrieved, citations, messages) and `events: TraceStep[]` |

## Providers & health

| Method & path | Returns |
|---|---|
| `GET /api/health` | `{status: 'ok', providers: {gemini: boolean, nvidia: boolean}}` |
| `GET /api/providers` | `{name, title, available, reason, signup_url, default_model}[]` |
| `GET /api/providers/{name}/models?kind=chat\|embed` | `{models: string[]}` (default first) |

If no provider is available, show a banner: "No LLM API key configured — add GEMINI_API_KEY or
NVIDIA_API_KEY to .env" with the signup links; chat will fail with an `error` event until then.
