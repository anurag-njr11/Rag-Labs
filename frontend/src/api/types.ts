/** Types mirrored from frontend/API.md (authoritative backend contract). */

export type Slot =
  | 'parse' | 'chunk' | 'embed' | 'vector_store' | 'cache' | 'compute' | 'retrieve' | 'rerank' | 'prompt' | 'generate'
  | 'verify'
export type Effect = 'rebuild' | 'instant'

/** Pipeline order. */
export const SLOTS: readonly Slot[] = [
  'parse', 'chunk', 'embed', 'vector_store', 'cache', 'compute', 'retrieve', 'rerank', 'prompt', 'generate', 'verify',
]

export interface NodeConfig {
  type: string
  [param: string]: unknown
}
/** A pipeline: every slot → { type, ...params }. Always contains all 11 slots. */
export type PipelineConfig = Record<Slot, NodeConfig>

export interface PipelineFieldError {
  slot: string
  field: string | null
  message: string
}

/** Loose JSON Schema shape (Pydantic output + RAGLabs extensions). */
export interface JSONSchemaProperty {
  title?: string
  description?: string
  type?: 'integer' | 'number' | 'boolean' | 'string' | 'array' | 'object' | 'null'
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  default?: unknown
  enum?: unknown[]
  enum_labels?: Record<string, string>
  items?: JSONSchemaProperty
  anyOf?: JSONSchemaProperty[]
  allOf?: JSONSchemaProperty[]
  $ref?: string
  const?: unknown
  widget?: string
  advanced?: boolean
  options_from?: string
  effect?: Effect
  [key: string]: unknown
}
export interface JSONSchema extends JSONSchemaProperty {
  properties?: Record<string, JSONSchemaProperty>
  required?: string[]
  $defs?: Record<string, JSONSchemaProperty>
}

// ---- GET /api/nodes -----------------------------------------------------
export interface SlotCatalog {
  slot: Slot
  title: string
  description: string
  effect: Effect
  types: NodeType[]
}
export interface NodeType {
  type: string
  title: string
  description: string
  available: boolean
  unavailable_reason: string
  exact: boolean | null
  exact_when: Record<string, unknown[]> | null
  schema: JSONSchema
  effects: Record<string, Effect>
  defaults: NodeConfig
}

// ---- projects ----------------------------------------------------------
export type IndexStatusValue = 'not_built' | 'pending' | 'building' | 'ready' | 'stale' | 'failed'

export interface BuildStats {
  docs_added: number
  docs_failed: number
  chunks_added: number
  parse_cache_hits: number
  chunk_cache_hits: number
  vectors_cached: number
  vectors_embedded: number
  dim?: number
  seconds: number
  store_notes: string[]
}
export interface IndexStatus {
  id?: string
  status: IndexStatusValue
  chunk_count: number
  store: string
  /** False when the retriever never queries the vector store (e.g. keyword-only). */
  dense?: boolean
  dim?: number | null
  error?: string | null
  stats?: BuildStats
  finished_at?: string | null
  job_id: string | null
}
export interface Change {
  slot: Slot
  field: string
  before: unknown
  after: unknown
  effect: Effect
}
export interface Version {
  id: string
  version: number
  note: string
  created_at: string
  index_config_hash: string
  parent_id: string | null
  active: boolean
  config: PipelineConfig
  index?: IndexStatus
  changes_from_parent?: Change[]
  parent_version?: number | null
  /** Detail only: each time this version was made active, newest first. */
  activations?: VersionActivation[]
}
export interface VersionActivation {
  at: string
  /** The version it replaced; null if it was the project's first. */
  previous_version: number | null
}
export interface ProjectSummary {
  /** Latest finished eval of the active version (absent if never measured). */
  quality?: { hit_at_k: number; k: number; n: number }
  vector_store: string
  dense?: boolean
  embed_model: string
  generate: string
  model: string
}
export interface Project {
  id: string
  name: string
  description: string
  created_at: string
  active_version_id: string | null
  documents: number
  versions: number
  active_version: Version | null
  index: IndexStatus | null
  summary?: ProjectSummary
}
export interface CreateProjectBody {
  name: string
  description?: string
  config?: PipelineConfig
}
export interface UpdateProjectBody {
  name?: string
  description?: string
}

// ---- pipelines & versions ---------------------------------------------
export type ValidateResult =
  | { valid: true; config: PipelineConfig; index_config_hash: string }
  | { valid: false; errors: PipelineFieldError[] }

export interface Estimate {
  kind: 'none' | 'reinsert' | 'reembed' | 'full'
  message: string
  chunks?: number
  documents?: number
}
export interface EstimateResult {
  changes: Change[]
  rebuild_needed: boolean
  estimate: Estimate
  index_config_hash: string
}
export interface VersionDiff {
  a: number
  b: number
  changes: Change[]
}
export interface CreateVersionBody {
  config: PipelineConfig
  note?: string
  activate?: boolean
  build?: boolean
}
export interface CreateVersionResult {
  version: Version
  job_id: string | null
  /** Regression guard: eval run started on the newest ready eval set (null when there is none). */
  eval_job_id: string | null
  unchanged: boolean
}
export interface VersionJobResult {
  version: Version
  job_id: string | null
}
export interface Build {
  id: string
  index_config_hash: string
  config: PipelineConfig
  store_type: string
  status: IndexStatusValue | string
  dim: number | null
  chunk_count: number
  error: string | null
  stats: BuildStats | null
  started_at: string | null
  finished_at: string | null
}

// ---- documents ---------------------------------------------------------
export interface ParseQuality {
  score: 'good' | 'fair' | 'poor'
  pages: number | null
  chars: number
  tables: number
  empty_pages: number[]
  empty_page_count: number
  ocr_used: boolean
  header_lines_removed: number
  warnings: string[]
}
export interface Document {
  id: string
  filename: string
  source_url: string | null
  mime: string
  size_bytes: number
  status: 'uploaded' | 'indexed' | 'failed'
  error: string | null
  parse_quality: ParseQuality | null
  created_at: string
  /** Chunks in the ACTIVE index; null = not indexed there yet. */
  chunks: number | null
  index_error: string | null
  /** Source file's / page's last-modified date (upload File.lastModified, HTTP Last-Modified); ISO. */
  last_modified: string | null
  okf: DocumentOkf & { usage_count: number }
}
/** OKF document fields (FR-2.30). From Markdown front matter or the Documents tab; editing never rebuilds. */
export interface DocumentOkf {
  /** OKF's one required key in a bundle (Guide, FAQ, Reference…); any value. */
  type?: string
  status?: string
  /** ISO date */
  stale_after?: string
  /** true, an ISO review date, or provenance like "human:alice@2026-05-01" / "process:ci" / "agent:writer" */
  verified?: boolean | string
  /** ISO timestamp the source says it was generated */
  generated?: string
  sources?: string[]
}
export interface OkfImportResult {
  created: { id: string; filename: string }[]
  duplicates: { id: string; filename: string }[]
  /** Non-Markdown files in the bundle (references, data, code) — not indexed. */
  skipped: { path: string; reason: string }[]
  errors: { path: string; error: string }[]
  job_id: string | null
}
export interface UploadResult {
  created: { id: string; filename: string }[]
  duplicates: { id: string; filename: string }[]
  errors: { filename: string; error: string }[]
  job_id: string | null
}
export interface AddUrlBody {
  url: string
  sitemap?: boolean
  max_pages?: number
  /** false = fetch only, don't build the index yet. Default true. */
  build?: boolean
}
export interface Chunk {
  id: string
  ordinal: number
  text: string
  token_count: number
  is_table: boolean
  page_start: number | null
  page_end: number | null
  heading_path: string
}
export interface ChunksResult {
  chunks: Chunk[]
  total: number
}

export const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.md', '.markdown', '.mdx', '.txt', '.rst', '.html', '.htm'] as const
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024

// ---- jobs --------------------------------------------------------------
export type JobStage =
  | 'fetch' | 'parse' | 'embed' | 'store' | 'keywords' | 'ready'
  | 'index' | 'generate' | 'validate' | 'evaluate' | 'sweep'
  | 'retrieve' | 'judge' | 'recheck' | 'scan' | 'contradictions' | 'answer' | 'grade' | 'grade_cells' | 'rejudge'
  | 'attack' | 'train' | 'bootstrap' | 'propose' | 'select' | 'test'
export const JOB_STAGES: readonly JobStage[] = ['fetch', 'parse', 'embed', 'store', 'keywords', 'ready']

export interface JobDoneResult {
  fetch?: { pages: number; created: number; duplicates: number; failed: number }
  /** Absent for fetch-only URL imports (`build: false`). */
  build?: { id: string; status: string; chunk_count: number; stats: BuildStats }
}
export type JobEvent =
  | { type: 'progress'; t: number; stage: JobStage; done: number; total: number; message: string }
  | { type: 'log'; t: number; level: 'info' | 'warning' | 'error'; message: string }
  | { type: 'done'; t: number; result: JobDoneResult }
  | { type: 'failed'; t: number; error: string }

export interface Job {
  id: string
  kind: string
  project_id: string
  status: 'running' | 'done' | 'failed'
  error: string | null
  result: JobDoneResult | null
  last: JobEvent | null
}

// ---- chat --------------------------------------------------------------
export type FoundBy = 'dense' | 'keyword' | 'exact'

export interface RetrievedChunk {
  id: string
  document_id: string
  document: string
  source_url: string | null
  ordinal: number
  text: string
  token_count: number
  is_table: boolean
  page_start: number | null
  page_end: number | null
  heading_path: string
  rank: number
  retrieval_rank: number
  score: number
  scores: Partial<Record<'dense' | 'keyword' | 'exact' | 'rerank', number>>
  ranks: Partial<Record<FoundBy, number>>
  found_by: FoundBy[]
  exact_keys: string[]
  /** Moved to the top: its heading names what was asked about (retrieve.pin_definitions). */
  pinned: boolean
  in_context: boolean
  context_n: number | null
  cited?: boolean
  /** retrieve.context_window > 0: ordinals of the chunks in `window_text` (this one ± neighbours). */
  window?: number[]
  /** What the prompt got for this hit: its text plus neighbours. `text` stays the hit's own. */
  window_text?: string
}
export interface Citation {
  n: number
  chunk_id: string
  document_id: string
  document: string
  page_start: number | null
  page_end: number | null
  heading_path: string
  spans: [number, number][]
  /** Grounding check: does this source support the claims citing it? Absent when Verify is off. */
  support?: Verdict | null
}
export type Verdict = 'yes' | 'partial' | 'no'
/** Result of the grounding check (Verify slot). `grounded`/`score` are null when the check call failed. */
export interface Verification {
  status: 'ok' | 'error'
  grounded: boolean | null
  score: number | null
  claims: { claim: string; supported: Verdict; cited: Record<string, Verdict> }[]
  /** Source number → worst verdict across the claims citing it. */
  citations: Record<string, Verdict>
  /** 0 = first answer; 1+ = after that many retries with more context. */
  attempt: number
  error?: string
}
export type TraceStepName =
  | 'embed_query' | 'dense_search' | 'keyword_search' | 'exact_search' | 'fuse' | 'pin' | 'mmr'
  | 'rerank' | 'prompt' | 'generate' | 'query_expansion' | 'context_window' | 'verify' | 'agent' | 'cache_lookup'
  | 'output_validation' | 'okf_policy' | 'compute_route' | 'compute' | 'execution'
/** Chat-to-build (FR-3.25): a proposed draft and its diff; nothing is saved. */
export interface BuildChatResult {
  config: PipelineConfig
  changes: Change[]
  explanation: string
  attempts: number
  rebuild?: boolean
  error?: string
}

/** Config prior (FR-3.27). */
export interface ConfigPrior {
  /** prior = predicted from sweeps on similar corpora; rules = no history, rule-based recommender. */
  source: 'prior' | 'rules'
  history: number
  fingerprint: Record<string, unknown>
  suggestions: {
    path: string
    value: string | number | boolean
    /** null for rules (not measured). */
    confidence: number | null
    votes?: number
    sweeps?: number
    mean_similarity?: number
    reason?: string
    current?: boolean
    skipped?: string
  }[]
  config: PipelineConfig
  verify_axes: { path: string; values: (string | number | boolean)[] }[]
}

/** Recipe gallery (FR-3.26). */
export interface Recipe {
  id: string
  name: string
  description: string
  tags: string[]
  builtin: boolean
  config: PipelineConfig
  created_at: string | null
  source_project?: string | null
}

/** API keys & usage (FR-3.23). */
export interface ApiKey {
  id: string
  name: string
  scope: 'chat' | 'admin'
  project_id: string | null
  /** First 9 characters, to recognise it. */
  prefix: string
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}
export interface UsageReport {
  days: number
  daily: { day: string; requests: number; errors: number; tokens_in: number; tokens_out: number; cost_usd: number; api: number }[]
  total: { requests: number; errors: number; tokens_in: number; tokens_out: number; cost_usd: number; api: number; playground: number }
  latency: { p50_ms: number | null; p95_ms: number | null }
  by_key: { id: string; name: string; prefix: string; requests: number }[]
}

/** Attested Computation (FR-3.21). */
export interface DataTable { table: string; columns: { name: string; type: string }[]; rows: number }
export interface ComputationParam {
  name: string
  type: 'integer' | 'number' | 'string' | 'date'
  required: boolean
  description: string
  options: string[] | null
}
export interface ComputationSpec {
  name: string
  description: string
  parameters: ComputationParam[]
  sql: string
  attester: { min_rows: number; max_rows: number; columns: string[]; non_null: boolean; bounds: Record<string, [number | null, number | null]> }
  unit: string
}
export interface Computation extends ComputationSpec { id: string; created_at: string; updated_at: string }
export interface ComputeReceipt {
  name: string
  computation_id?: string
  parameters: Record<string, unknown>
  sql: string
  result: { columns: string[]; rows: unknown[][]; truncated: boolean; ms: number } | null
  checks: { check: string; ok: boolean; detail: string }[]
  /** Only an attested result is shown as the answer. */
  attested: boolean
  answer: string | null
  error?: string
}

/** Code check (verify.type = execution_check, FR-3.13–3.16). */
export type ExecutionStatus = 'verified' | 'unverified' | 'ran_without_tests' | 'missing_dependency' | 'sandbox_unavailable' | 'not_applicable'
export interface Execution {
  status: ExecutionStatus
  /** provided (the question's own) · doctest (>>> examples in the docs) · generated (weaker evidence) · none */
  test_source?: 'provided' | 'doctest' | 'generated' | 'none'
  tests?: string
  attempts?: number
  steps: { step: number; ok: boolean; stage?: string; tests_run?: number | null; detail: string; ms: number }[]
  error?: string
}

/** Answered from the semantic cache (cache slot): the earlier question it matched. */
export interface CacheHit {
  question: string
  similarity: number
  created_at: string
  /** The run that produced the cached answer. */
  run_id: string | null
}
export interface TraceStep {
  seq: number
  step: TraceStepName
  ms: number
  tokens_in: number
  tokens_out: number
  cost_usd: number
  payload: Record<string, unknown>
  /** Offset from the run's start; null/absent on runs recorded before it existed. */
  start_ms?: number | null
}
export interface ChatTotals {
  ms: number
  tokens_in: number
  tokens_out: number
  cost_usd: number
  latency_ms: number
}
export type ChatEvent =
  | { type: 'status'; message: string; job_id: string }
  | { type: 'step'; step: TraceStepName; ms: number; hit?: boolean }
  | { type: 'run'; run_id: string; version: number; build_id: string; store: string }
  | { type: 'retrieval'; results: RetrievedChunk[]; trace: TraceStep[] }
  | { type: 'token'; text: string }
  | { type: 'verifying'; what?: 'code' }
  | { type: 'execution'; execution: Execution }
  | { type: 'verify'; verification: Verification }
  | { type: 'retry'; attempt: number; reason: string }
  | {
      type: 'done'
      run_id: string
      answer: string
      citations: Citation[]
      retrieved: RetrievedChunk[]
      trace: TraceStep[]
      totals: ChatTotals
      truncated: boolean
      verification: Verification | null
      /** Set when the answer came from the semantic cache (no retrieval, no LLM call). */
      cache?: CacheHit | null
      /** Compute slot: the computation the question was routed to (attested or not). */
      computation?: ComputeReceipt | null
      execution?: Execution | null
    }
  | { type: 'error'; code: string; message: string }

export interface ChatBody {
  question: string
  version_id?: string
}
export interface ChatSource {
  rank: number
  document: string
  page_start: number | null
  page_end: number | null
  heading_path: string
  found_by: FoundBy[]
  scores: RetrievedChunk['scores']
  cited: boolean
  text: string
}
/** Non-streaming chat response (`stream: false`). */
export interface ChatResult {
  answer: string
  citations: Citation[]
  sources: ChatSource[]
  run_id: string
  totals: ChatTotals
}
/** `GET /projects/{id}/suggestions`: the first source that yields questions wins. */
export interface Suggestions {
  source: 'eval' | 'headings' | 'recent' | 'none'
  questions: string[]
}
export interface RunSummary {
  id: string
  version_id: string
  question: string
  status: string
  latency_ms: number | null
  tokens_in: number | null
  tokens_out: number | null
  cost_usd: number | null
  created_at: string
}
export interface RunDetail extends RunSummary {
  result: {
    answer?: string
    retrieved?: RetrievedChunk[]
    citations?: Citation[]
    messages?: unknown[]
    verification?: Verification | null
    cache?: CacheHit | null
    computation?: ComputeReceipt | null
    execution?: Execution | null
    [k: string]: unknown
  } | null
  events: TraceStep[]
  [k: string]: unknown
}

// ---- providers & health -----------------------------------------------
export interface Health {
  status: 'ok'
  providers: Record<string, boolean>
}
/** Where a provider's settings come from (later sources override earlier ones per field). */
export type ProviderSource = 'preset' | 'env' | 'ui' | 'custom-env' | 'custom-ui'

/** An LLM provider for the Generate slot — a built-in preset or a custom OpenAI-compatible endpoint. */
export interface Provider {
  name: string
  title: string
  description: string
  base_url: string
  default_model: string
  signup_url: string
  key_required: boolean
  supports_reasoning: boolean
  /** Names of extra HTTP headers sent with each request (values never leave the backend). */
  headers: string[]
  source: ProviderSource
  /** Preset id, or null for a custom endpoint. */
  preset: string | null
  custom: boolean
  key_set: boolean
  /** "…abcd" — the key itself is never returned. */
  key_hint: string
  /** Env var the backend also reads the key from, e.g. OPENAI_API_KEY. */
  key_env: string
  available: boolean
  reason: string
  /** Offered as a Generate type. */
  enabled: boolean
}

/** Create/update body. Omitted fields keep their value; an empty api_key keeps the stored key. */
export interface ProviderInput {
  name?: string
  title?: string
  base_url?: string
  api_key?: string
  default_model?: string
  supports_reasoning?: boolean
  key_required?: boolean
  headers?: Record<string, string>
}

export interface ProviderTestResult {
  ok: boolean
  error?: string
  models?: number
  sample?: string[]
  ms: number
}
export interface ModelList {
  models: string[]
}
export type ModelKind = 'chat' | 'embed'

// ---- evaluation ------------------------------------------------------------
export type EvalStatus = 'running' | 'ready' | 'failed'

export interface EvalSetStats {
  sampled: number
  generated: number
  kept: number
  too_generic: number
  bad_evidence: number
  other: number
}
export interface EvalItem {
  id: string
  ordinal: number
  question: string
  gold_answer: string
  evidence: string
  document_id: string
  document: string | null
  gold_chunk_id: string
  valid: boolean
  reject_reason: string | null
  closed_book_answer: string | null
  /** Required facts a complete answer states (FR-2.6); [] on older items. */
  facets: string[]
  /** Python asserts the answer's code must pass (FR-3.17); null when none. */
  tests?: string | null
}
export interface EvalSet {
  id: string
  project_id: string
  version_id: string | null
  build_id: string | null
  status: EvalStatus
  size_requested: number
  stats: Partial<EvalSetStats>
  error: string | null
  created_at: string
  /** +1 on every hand edit or import (FR-2.5). */
  revision: number
  /** sha256 of the sorted document content hashes at generation; null on older sets. */
  corpus_sha: string | null
  /** The project's documents differ from those the set was generated from; null = not recorded (older sets). */
  corpus_changed: boolean | null
}
export interface EvalSetDetail extends EvalSet {
  items: EvalItem[]
}

export type EvalDiagnosis =
  | 'incorrect_format' | 'incomplete_answer' | 'wrong_specificity' | 'failed_to_extract'
  | 'dropped_by_budget' | 'dropped_by_rerank' | 'ranked_below_k' | 'not_retrieved'
export type Grade = 'yes' | 'partial' | 'no'
export type Specificity = 'ok' | 'too_vague' | 'too_verbose'
/** Answer grader; omitted = the version's own Generate model. */
export interface Judge {
  provider: string
  model: string
}

/** LLM-graded answers (only on runs started with `answers: true`). */
export interface AnswerSummary {
  n: number
  ungraded: number
  correct: number
  partial: number
  wrong: number
  correct_rate: number
  /** 95% Wilson interval for correct_rate. */
  correct_ci: [number, number]
  grounded_rate: number
  relevant_rate?: number
  /** Rank-weighted share of in-context passages the judge found relevant (null = none scored; absent on older runs). */
  context_precision?: number | null
  /** Share of required facts (else the gold answer) the judge found supported by the context. */
  context_recall?: number | null
  /** USD per 1,000 queries at list price: query expansion + answer generation. null = a model has no known price. */
  cost_per_1k?: number | null
  /** "provider/model" that graded. */
  judge?: string
  /** Sweep cell re-judged 3x with the per-question median (its interval overlapped the leader's). */
  rejudged?: boolean
  /** Answer time per question: generation + grounding checks + retries (absent on older runs). */
  answer_p50_ms?: number
  answer_p95_ms?: number
  /** Grounding-check roll-up — only when the version's Verify slot is on. */
  verify?: { checked: number; errors: number; pass_rate: number | null; retried: number; mean_score: number | null }
  /** FR-3.17: share of questions with tests whose answer's code passed them in the sandbox. */
  exec_verified_rate?: number
  exec_verified_ci?: [number, number]
  execution?: Record<ExecutionStatus, number> & { tested: number }
}

export interface EvalConfigSummary {
  parse: string
  chunk: string
  embed: string
  store: string
  dense?: boolean
  retrieve: string
  top_k: number
  rerank: string
  /** A bring-your-own RAG's URL (the pipeline fields above are then blank). */
  external?: string
}
export interface EvalMetrics {
  /** 95% intervals for the retrieval metrics (absent on runs made before they were added). */
  ci?: Partial<Record<'hit_at_1' | 'hit_at_3' | 'hit_at_k' | 'mrr', [number, number]>>
  n: number
  k: number
  hit_at_1: number
  hit_at_3: number
  hit_at_k: number
  mrr: number
  /** Binary-relevance nDCG@k (absent on older runs). */
  ndcg_at_k?: number
  p50_ms: number
  p95_ms?: number
  /** Share of questions whose evidence survives the prompt's context budget (absent on older runs). */
  context_hit?: number
  /** Mean tokens of context sent to the model per question (absent on older runs). */
  ctx_tokens?: number
  /** USD per 1,000 queries at list price for the retrieval stage (query expansion only). null = unknown price. */
  cost_per_1k?: number | null
  /** Size of the build that was scored. */
  index?: { chunks: number; vectors: number; bytes: number }
  answers?: AnswerSummary
  diagnoses: Record<EvalDiagnosis, number>
  config: EvalConfigSummary
}
export interface EvalItemResult {
  item_id: string
  rank: number | null
  hit: boolean
  diagnosis: EvalDiagnosis | null
  deep_rank: number | null
  in_context?: boolean
  ctx_tokens?: number
  /** List-price LLM cost of this question: query expansion (+ answer generation when graded); null = unknown. */
  cost_usd?: number | null
  /** Answer grading only. */
  context_precision?: number | null
  context_recall?: number | null
  answer?: string
  correct?: Grade
  grounded?: Grade | null
  relevant?: Grade | null
  specificity?: Specificity | null
  /** Required facts the judge found missing (items with facets only). */
  missing_facts?: string[]
  /** Broken citation contract, e.g. "no [n] citations". */
  format_error?: string
  ms: number
  top: { id: string; document: string; heading_path: string; hit: boolean }[]
  /** External systems: the trace id this question was sent with (`traceparent`). */
  trace_id?: string | null
  /** External systems: the OpenTelemetry spans it exported for this question (FR-4.7). */
  steps?: ExternalStep[]
}
/** One span an external system exported, as a step. `start_ms` is relative to the question's first span. */
export interface ExternalStep {
  seq: number
  step: string
  start_ms: number
  ms: number
  tokens_in: number
  tokens_out: number
  cost_usd: number
  /** The span with no parent: the whole request. */
  root: boolean
  payload: { model?: string | null; priced?: boolean }
}
export interface ExternalStepSummary {
  step: string
  n: number
  /** Median start offset; rows come in this order. */
  start_ms: number
  p50_ms: number
  p95_ms: number
  tokens_in: number
  tokens_out: number
}
export interface EvalRun {
  id: string
  eval_set_id: string
  version_id: string
  version: number | null
  /** Name of the bring-your-own RAG this run scored (`version_id` is then its id, `version` null). */
  external: string | null
  build_id: string | null
  status: EvalStatus
  error: string | null
  created_at: string
  /** The eval set's revision this run scored (null on older runs). */
  set_revision: number | null
  metrics: EvalMetrics | null
}
/** A RAG system running elsewhere, scored over HTTP (PRD §8.7). Header values are never returned. */
export interface ExternalConfig {
  url: string
  headers?: Record<string, string>
  question_field: string
  answer_path: string
  contexts_path: string
  text_path: string
  source_path: string
  top_k: number
  timeout_s: number
}
export interface ExternalSystem {
  id: string
  name: string
  created_at: string
  config: Omit<ExternalConfig, 'headers'> & { header_names: string[] }
}
export interface ExternalTestResult {
  question: string
  ms: number
  answer: string | null
  contexts: { text: string; external_source: string; score: number | null }[]
}
export interface EvalRunDetail extends EvalRun {
  results: EvalItemResult[]
  /** External systems that export OpenTelemetry spans: per step, across questions (root spans left out). */
  trace_summary?: ExternalStepSummary[]
}

// ---- sweeps ----------------------------------------------------------------
export type SweepStatus = 'running' | 'ready' | 'failed' | 'cancelled'
export type SweepCellStatus = 'pending' | 'running' | 'ready' | 'failed' | 'invalid' | 'skipped'

/** Domain embedding adapter (FR-3.10): a query-side matrix trained on an eval set. */
export interface RankScores { recall_at_k: number; mrr: number; n: number }
export interface Adapter {
  id: string
  version_id: string | null
  version: number | null
  eval_set_id: string | null
  status: 'running' | 'ready' | 'failed'
  error: string | null
  created_at: string
  embed_key: string | null
  dim: number | null
  metrics: {
    questions: number
    train: number
    /** Scored on questions the adapter never saw (dense-only ranking of every chunk). */
    holdout: { before: RankScores; after: RankScores }
    /** In-sample: the saved adapter, refitted on every question. */
    full: { before: RankScores; after: RankScores }
    chunks: number
    dim: number
    generalises: boolean
    /** Beat the plain embedder in cross-validation AND on the unseen holdout (absent on older adapters). */
    recommended?: boolean
    cv_passed?: boolean
    params: Record<string, number>
    /** Mean held-out-fold MRR per λ tried, and for the plain embedder (`identity`). */
    cv?: Record<string, number>
  } | null
}

/** Prompt optimisation run (FR-3.11). Scores: token F1 vs the gold answer, halved without citations. */
export interface PromptRun {
  id: string
  version_id: string | null
  version: number | null
  eval_set_id: string | null
  status: 'running' | 'ready' | 'failed'
  error: string | null
  created_at: string
  result: {
    splits: { train: number; val: number; test: number }
    candidates: { extra_instructions: string; examples: string; val_score: number; answered: number; is_current: boolean }[]
    best: { extra_instructions: string; examples: string; is_current: boolean }
    /** On test questions never used to choose. */
    test: { before: number; after: number; n: number }
    improves: boolean
    demos: number
    samples: { question: string; gold: string; before: string; before_score: number; after: string | null; after_score: number | null }[]
  } | null
}

/** Injection-resistance test (FR-3.7/3.8). */
export type InjectionOutcome = 'hijacked' | 'caught_by_check' | 'caught_by_filter' | 'resisted'
export type InjectionDefence = 'data_rule' | 'delimited' | 'source_labels' | 'output_validation' | 'grounding_check'
export interface InjectionVariant {
  id: 'current' | 'none' | 'all' | InjectionDefence
  label: string
  defences: InjectionDefence[]
  trials: number
  hijacked: number
  caught_by_check: number
  caught_by_filter: number
  resisted: number
  /** 1 − hijacked / trials; null when no trial finished. */
  score: number | null
  /** 95% Wilson interval for score (absent on older runs). */
  score_ci?: [number, number]
  by_payload: Record<string, { trials: number; hijacked: number }>
}
export interface InjectionRun {
  id: string
  version_id: string | null
  version: number | null
  eval_set_id: string | null
  status: 'running' | 'ready' | 'failed'
  error: string | null
  created_at: string
  options: { questions?: number; compare?: boolean }
  metrics: {
    questions: number
    failed_trials: number
    payloads: { id: string; label: string; goal: string }[]
    variants: InjectionVariant[]
  } | null
  /** Detail only: one row per trial. */
  results?: { variant: string; payload: string; outcome: InjectionOutcome; answer: string; removed: string[]; question: string; item_id: string }[]
}

export interface SweepAxis {
  path: string
  label: string
  effect: Effect
  values: (string | number | boolean)[]
  /** Only offer the axis when the base config matches, e.g. {"embed.type": "fastembed"}. */
  requires?: Record<string, string>
  /** Per-value tooltip, e.g. "MTEB retrieval 54.4 · 640 MB". */
  notes?: Record<string, string>
  /** Per-value benchmark score shown on the chip (null = not reported). */
  scores?: Record<string, number | null>
  /** Suggested starting values, e.g. the top 3 embedders by MTEB retrieval. */
  seed?: SweepAxis['values']
  /** Only answer-side settings change: needs answer grading (Auto-Optimize) to compare. */
  answers_only?: boolean
}
export interface SweepAxes {
  axes: SweepAxis[]
  max_cells: number
}
export interface SweepCell {
  overrides: Record<string, string | number | boolean>
  config: PipelineConfig | null
  status: SweepCellStatus
  error: string | null
  metrics?: EvalMetrics & {
    ctx_tokens: number
    context_hit: number
    /** Tokens a query sends to LLMs: the answer prompt's context + retrieval-side calls (query expansion,
     *  agent planning). The Pareto cost axis; absent on sweeps from before it existed (use ctx_tokens). */
    query_tokens?: number
  }
  build_id?: string
  /** On the quality (MRR) vs. LLM-tokens-per-query Pareto frontier. */
  pareto?: boolean
  /** Auto-Optimize: why answer grading failed for this cell. */
  grade_error?: string
}
export interface Sweep {
  id: string
  project_id: string
  eval_set_id: string
  base_version_id: string
  base_version: number | null
  axes: { path: string; values: SweepAxis['values'] }[]
  cells: SweepCell[]
  counts: Partial<Record<SweepCellStatus, number>>
  status: SweepStatus
  error: string | null
  created_at: string
}

// ---- corpus health -----------------------------------------------------------
export type GapVerdict = 'covered' | 'partial' | 'missing'

export interface HealthExcerpt {
  chunk_id: string
  document_id: string
  document: string
  heading_path: string
  page_start: number | null
  text: string
}
export interface CoverageSummary {
  n: number
  covered: number
  partial: number
  missing: number
  covered_rate: number
  ungraded: number
  /** Gaps a deep retrieval answers: the content exists, retrieval missed it. Absent in older reports. */
  retrieval_miss?: number
  sources: { pasted: number; history: number }
}
export interface GapTopic {
  /** What the docs need to add (the judge's words), or the first question. */
  topic: string
  count: number
  missing: number
  partial: number
  questions: { question: string; verdict: GapVerdict; source: 'pasted' | 'history'; passages: HealthExcerpt[] }[]
}
export interface PassagePair {
  a: HealthExcerpt
  b: HealthExcerpt
  similarity: number
  explanation?: string
}
export interface DocumentUsage {
  document_id: string
  document: string
  chunks: number
  used: number
}
export type StaleReason = 'deprecated' | 'past_stale_after' | 'old'
export interface StaleDocument {
  document_id: string
  document: string
  reasons: StaleReason[]
  status: string | null
  stale_after: string | null
  last_modified: string | null
  age_days: number | null
}
export interface HealthResult {
  coverage: {
    summary: CoverageSummary
    /** Content gaps only; retrieval misses are listed separately. */
    topics: GapTopic[]
    retrieval_misses?: { question: string; verdict: GapVerdict; source: 'pasted' | 'history' }[]
  }
  /** Absent in reports made before staleness existed. */
  staleness?: { max_age_days: number; documents_checked: number; with_dates: number; documents: StaleDocument[] }
  duplicates: PassagePair[]
  contradictions: PassagePair[]
  pairs_checked: number
  usage: { questions: number; chunks: number; chunks_used: number; unused_documents: number; documents: DocumentUsage[] }
  /** Against the previous ready report (null for the first). */
  trend?: HealthTrend | null
}
export interface HealthTrend {
  previous_covered_rate: number | null
  covered_rate_change: number | null
  /** Questions in both reports: gap → covered, covered → gap. */
  resolved: number
  regressed: number
  new_gaps: number
  new_questions: number
}
/** Production loop (FR-3.22). */
export interface HealthMonitor {
  settings: { enabled: boolean; every_n: number; sources: 'all' | 'api'; stale_days: number }
  since_last_report: { last_report_at: string | null; api: number; playground: number; all: number }
}
export interface HealthReport {
  /** manual, or auto (started by the production-loop monitor). */
  trigger?: 'manual' | 'auto'
  /** Which history questions it used: all, or API traffic only. */
  sources?: 'all' | 'api'
  id: string
  project_id: string
  version_id: string
  version: number | null
  build_id: string | null
  status: EvalStatus
  error: string | null
  created_at: string
  /** Detail only. */
  result?: HealthResult | null
  /** List only. */
  summary?: (CoverageSummary & { topics: number; contradictions: number; duplicates: number; unused_documents: number; stale_documents: number }) | null
}

/** A one-click fix for a miss diagnosis: the full config to save as a new version. */
export interface EvalFix {
  diagnosis: EvalDiagnosis
  config: PipelineConfig
  changes: Change[]
  base_version: number | null
}
