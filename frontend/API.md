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
| `POST /api/projects/{id}/versions` | `{config, note?, activate?=true, build?=true}` | `201 {version: Version, job_id: string\|null, unchanged: boolean}` — `unchanged: true` if identical to active (no new version) |
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
| `POST /api/projects/{id}/documents?build=true` | multipart, field `files` repeated | `201 {created: {id, filename}[], duplicates: {id, filename}[], errors: {filename, error}[], job_id: string\|null}` |
| `POST /api/projects/{id}/documents/url` | `{url, sitemap?: boolean, max_pages?: number, build?: boolean = true}` | `202 {job_id}` — job fetches, then builds (`build: false` = fetch only; the job's result has no `build`) |
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
| `POST /sets/{set_id}/runs` | `{version_id?}` (default active) | 201 `{run: EvalRun, job_id}` · 409 set not ready |
| `GET /runs?set_id=` | | `EvalRun[]` oldest first (no `results`) |
| `GET /runs/{run_id}` | | `EvalRun & {results: EvalItemResult[]}` |

```ts
EvalSet = {id, project_id, version_id, build_id, status, size_requested, error, created_at,
           stats: {sampled, generated, kept, too_generic, bad_evidence, other}}
EvalItem = {id, ordinal, question, gold_answer, evidence, document_id, document, gold_chunk_id,
            valid, reject_reason, closed_book_answer}
EvalRun = {id, eval_set_id, version_id, version, build_id, status, error, created_at,
           metrics: {n, k, hit_at_1, hit_at_3, hit_at_k, mrr, p50_ms,
                     diagnoses: {dropped_by_rerank, ranked_below_k, not_retrieved},
                     config: {parse, chunk, embed, store, retrieve, top_k, rerank}} | null}
EvalItemResult = {item_id, rank: number | null, hit, diagnosis: 'dropped_by_rerank' | 'ranked_below_k' | 'not_retrieved' | null,
                  deep_rank, ms, top: {id, document, heading_path, hit}[]}
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
      | 'rerank' | 'prompt' | 'generate'
  ms: number; tokens_in: number; tokens_out: number; cost_usd: number
  payload: Record<string, unknown>  // e.g. {hits: 12, store: 'faiss', exact: true} / {included: 5, dropped: 2}
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
