/** Types mirrored from frontend/API.md (authoritative backend contract). */

export type Slot = 'parse' | 'chunk' | 'embed' | 'vector_store' | 'retrieve' | 'rerank' | 'prompt' | 'generate'
export type Effect = 'rebuild' | 'instant'

/** Pipeline order. */
export const SLOTS: readonly Slot[] = ['parse', 'chunk', 'embed', 'vector_store', 'retrieve', 'rerank', 'prompt', 'generate']

export interface NodeConfig {
  type: string
  [param: string]: unknown
}
/** A pipeline: every slot → { type, ...params }. Always contains all 8 slots. */
export type PipelineConfig = Record<Slot, NodeConfig>

export interface PipelineFieldError {
  slot: string
  field: string | null
  message: string
}

/** Loose JSON Schema shape (Pydantic output + RAG Builder extensions). */
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
}
export interface ProjectSummary {
  vector_store: string
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
  | 'index' | 'generate' | 'validate' | 'evaluate'
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
}
export type TraceStepName =
  | 'embed_query' | 'dense_search' | 'keyword_search' | 'exact_search' | 'fuse' | 'pin' | 'mmr'
  | 'rerank' | 'prompt' | 'generate'
export interface TraceStep {
  seq: number
  step: TraceStepName
  ms: number
  tokens_in: number
  tokens_out: number
  cost_usd: number
  payload: Record<string, unknown>
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
  | { type: 'run'; run_id: string; version: number; build_id: string; store: string }
  | { type: 'retrieval'; results: RetrievedChunk[]; trace: TraceStep[] }
  | { type: 'token'; text: string }
  | {
      type: 'done'
      run_id: string
      answer: string
      citations: Citation[]
      retrieved: RetrievedChunk[]
      trace: TraceStep[]
      totals: ChatTotals
      truncated: boolean
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
export interface Provider {
  name: string
  title: string
  available: boolean
  reason: string
  signup_url: string
  default_model: string
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
}
export interface EvalSetDetail extends EvalSet {
  items: EvalItem[]
}

export type EvalDiagnosis = 'dropped_by_rerank' | 'ranked_below_k' | 'not_retrieved'

export interface EvalConfigSummary {
  parse: string
  chunk: string
  embed: string
  store: string
  retrieve: string
  top_k: number
  rerank: string
}
export interface EvalMetrics {
  n: number
  k: number
  hit_at_1: number
  hit_at_3: number
  hit_at_k: number
  mrr: number
  p50_ms: number
  diagnoses: Record<EvalDiagnosis, number>
  config: EvalConfigSummary
}
export interface EvalItemResult {
  item_id: string
  rank: number | null
  hit: boolean
  diagnosis: EvalDiagnosis | null
  deep_rank: number | null
  ms: number
  top: { id: string; document: string; heading_path: string; hit: boolean }[]
}
export interface EvalRun {
  id: string
  eval_set_id: string
  version_id: string
  version: number | null
  build_id: string | null
  status: EvalStatus
  error: string | null
  created_at: string
  metrics: EvalMetrics | null
}
export interface EvalRunDetail extends EvalRun {
  results: EvalItemResult[]
}
