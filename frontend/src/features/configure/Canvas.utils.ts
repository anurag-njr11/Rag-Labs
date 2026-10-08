import type { PipelineConfig, Slot } from '@/api/types'

export interface GNode {
  id: string
  /** The slot it edits (several nodes can share one, e.g. retrieval paths). */
  slot?: Slot
  title: string
  sub: string
  col: number
  row: number
  /** Present but turned off in this config (drawn ghosted). */
  off?: boolean
  io?: boolean
}
export interface GEdge {
  from: string
  to: string
  label?: string
  /** branch = an early exit or a loop; index = feeds the query side from the index. */
  kind?: 'flow' | 'branch' | 'index'
}

export const PATHS = ['dense', 'keyword', 'exact'] as const
export type Path = (typeof PATHS)[number]
const MODE_PATHS: Record<string, Path[]> = { fused: ['dense', 'keyword', 'exact'], hybrid: ['dense', 'keyword'], dense: ['dense'], keyword: ['keyword'] }

/** The retrieve type that runs exactly these paths, or null if no retriever does (e.g. exact alone). */
export function modeFor(paths: Path[]): string | null {
  const key = [...paths].sort().join(',')
  return Object.entries(MODE_PATHS).find(([, p]) => [...p].sort().join(',') === key)?.[0] ?? null
}

const s = (v: unknown) => (v === undefined || v === null ? '' : String(v))

/** The real execution graph of a pipeline: the query lane with its branches, and the index lane. */
export function buildGraph(cfg: PipelineConfig): { nodes: GNode[]; edges: GEdge[] } {
  const rt = cfg.retrieve as Record<string, unknown>
  const agentic = rt.type === 'agentic'
  const active = MODE_PATHS[agentic ? s(rt.search_mode) || 'fused' : s(rt.type)] ?? []
  const cacheOn = cfg.cache?.type !== undefined && cfg.cache.type !== 'none'
  const computeOn = cfg.compute?.type !== undefined && cfg.compute.type !== 'none'
  const verify = (cfg.verify ?? { type: 'none' }) as Record<string, unknown>
  const verifyOn = verify.type !== 'none' || !!verify.validate_output
  const qe = s(rt.query_expansion) || 'none'
  const nodes: GNode[] = [
    { id: 'question', title: 'Question', sub: 'Playground / API', col: 0, row: 2, io: true },
    { id: 'cache', slot: 'cache', title: 'Cache', sub: cacheOn ? `semantic ≥ ${s(cfg.cache.threshold)}` : 'off', col: 1, row: 2, off: !cacheOn },
    { id: 'compute', slot: 'compute', title: 'Compute', sub: computeOn ? 'attested computations' : 'off', col: 2, row: 2, off: !computeOn },
    agentic
      ? { id: 'expand', slot: 'retrieve', title: 'Agent planner', sub: `≤ ${s(rt.max_steps)} steps${rt.offload ? ' · offload' : ''}`, col: 3, row: 2 }
      : { id: 'expand', slot: 'retrieve', title: 'Query expansion', sub: qe === 'none' ? 'off' : qe.replace('_', ' '), col: 3, row: 2, off: qe === 'none' },
    { id: 'path-dense', slot: 'retrieve', title: 'Dense search', sub: s(cfg.vector_store.type), col: 4, row: 1, off: !active.includes('dense') },
    { id: 'path-keyword', slot: 'retrieve', title: 'Keyword search', sub: 'BM25 · SQLite FTS5', col: 4, row: 2, off: !active.includes('keyword') },
    { id: 'path-exact', slot: 'retrieve', title: 'Exact lookup', sub: 'errors · symbols', col: 4, row: 3, off: !active.includes('exact') },
    { id: 'fuse', slot: 'retrieve', title: 'Fuse & rank', sub: `${s(rt.fusion).toUpperCase()} · top ${s(rt.top_k)}${rt.mmr ? ' · MMR' : ''}${rt.okf_policy ? ' · OKF' : ''}`, col: 5, row: 2 },
    { id: 'rerank', slot: 'rerank', title: 'Rerank', sub: cfg.rerank.type === 'none' ? 'off' : `keep ${s(cfg.rerank.top_n)}`, col: 6, row: 2, off: cfg.rerank.type === 'none' },
    { id: 'prompt', slot: 'prompt', title: 'Prompt', sub: `${s(cfg.prompt.type).replace('_', ' ')} · ${s(cfg.prompt.max_context_tokens)} tok`, col: 7, row: 2 },
    { id: 'generate', slot: 'generate', title: 'Generate', sub: s(cfg.generate.model) || s(cfg.generate.type), col: 8, row: 2 },
    { id: 'verify', slot: 'verify', title: 'Verify', sub: verify.type === 'grounding_check' ? 'grounding check' : verify.validate_output ? 'output validation' : 'off', col: 9, row: 2, off: !verifyOn },
    { id: 'answer', title: 'Answer', sub: 'with citations', col: 10, row: 2, io: true },
    { id: 'parse', slot: 'parse', title: 'Parse', sub: s(cfg.parse.type), col: 1, row: 5 },
    { id: 'chunk', slot: 'chunk', title: 'Chunk', sub: `${s(cfg.chunk.type).replace('_', ' ')} · ${s(cfg.chunk.size)}`, col: 2, row: 5 },
    { id: 'embed', slot: 'embed', title: 'Embed', sub: s(cfg.embed.model) || s(cfg.embed.type), col: 3, row: 5 },
    { id: 'vector_store', slot: 'vector_store', title: 'Vector store', sub: s(cfg.vector_store.type), col: 4, row: 5 },
  ]
  const flow = (ids: string[]): GEdge[] => ids.slice(1).map((to, i) => ({ from: ids[i], to }))
  const edges: GEdge[] = [
    ...flow(['question', 'cache', 'compute', 'expand']),
    ...PATHS.map((p) => ({ from: 'expand', to: `path-${p}` })),
    ...PATHS.map((p) => ({ from: `path-${p}`, to: 'fuse' })),
    ...flow(['fuse', 'rerank', 'prompt', 'generate', 'verify', 'answer']),
    ...flow(['parse', 'chunk', 'embed', 'vector_store']),
    { from: 'vector_store', to: 'path-dense', label: 'vectors', kind: 'index' },
    { from: 'chunk', to: 'path-keyword', label: 'text', kind: 'index' },
    { from: 'chunk', to: 'path-exact', label: 'keys', kind: 'index' },
  ]
  if (cacheOn) edges.push({ from: 'cache', to: 'answer', label: 'hit', kind: 'branch' })
  if (computeOn) edges.push({ from: 'compute', to: 'answer', label: 'attested', kind: 'branch' })
  if (agentic) edges.push({ from: 'fuse', to: 'expand', label: 'search again', kind: 'branch' })
  if (verify.type === 'grounding_check' && verify.on_fail === 'retry_with_more_context' && Number(verify.max_retries) > 0) {
    edges.push({ from: 'verify', to: 'fuse', label: 'retry · more context', kind: 'branch' })
  }
  return { nodes, edges }
}
