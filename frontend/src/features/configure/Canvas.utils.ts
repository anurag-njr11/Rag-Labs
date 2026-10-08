import type { ChatEvent, PipelineConfig, Slot, TraceStep, TraceStepName } from '@/api/types'

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

/** Whether queries touch the vector store; mirrors backend `dense_used`. Else Embed / Vector store are built but idle. */
export function denseUsed(cfg: PipelineConfig): boolean {
  const rt = cfg.retrieve as Record<string, unknown>
  const mode = rt.type === 'agentic' ? String(rt.search_mode ?? 'fused') : String(rt.type)
  return (MODE_PATHS[mode] ?? []).includes('dense') || !!rt.mmr
}

const s = (v: unknown) => (v === undefined || v === null ? '' : String(v))

/** Rows of the layout: indexing on top, the retrieval block (paths stacked around the main row), then the
 *  answering lane below. Columns are compact, so what is off or folded away leaves no gap. */
export const ROWS = { index: 0, main: 2, answer: 5 }

/** The real execution graph of a pipeline. The query side wraps into two lanes — question → retrieval → rerank,
 *  then (right to left, under it) prompt → generate → verify → answer — so it fits at a readable size. Expansion
 *  is drawn only when it is on, and "Fuse" only when two or more retrievers feed it. */
export function buildGraph(cfg: PipelineConfig): { nodes: GNode[]; edges: GEdge[] } {
  const rt = cfg.retrieve as Record<string, unknown>
  const agentic = rt.type === 'agentic'
  const active = MODE_PATHS[agentic ? s(rt.search_mode) || 'fused' : s(rt.type)] ?? []
  const cacheOn = cfg.cache?.type !== undefined && cfg.cache.type !== 'none'
  const computeOn = cfg.compute?.type !== undefined && cfg.compute.type !== 'none'
  const verify = (cfg.verify ?? { type: 'none' }) as Record<string, unknown>
  const verifyOn = verify.type !== 'none' || !!verify.validate_output
  const qe = s(rt.query_expansion) || 'none'
  const dense = denseUsed(cfg)
  const showExpand = agentic || qe !== 'none'
  const showFuse = active.length > 1

  let c = 3
  const expandCol = showExpand ? c++ : -1
  const pathsCol = c++
  const fuseCol = showFuse ? c++ : -1
  const rerankCol = c
  const R = ROWS
  const nodes: GNode[] = [
    { id: 'question', title: 'Question', sub: 'Playground / API', col: 0, row: R.main, io: true },
    { id: 'cache', slot: 'cache', title: 'Cache', sub: cacheOn ? `Semantic, similarity ≥ ${s(cfg.cache.threshold)}` : 'Off', col: 1, row: R.main, off: !cacheOn },
    { id: 'compute', slot: 'compute', title: 'Compute', sub: computeOn ? 'Attested computations' : 'Off', col: 2, row: R.main, off: !computeOn },
    ...(showExpand ? [agentic
      ? { id: 'expand', slot: 'retrieve' as Slot, title: 'Agent planner', sub: `Up to ${s(rt.max_steps)} steps${rt.offload ? ' · offload' : ''}`, col: expandCol, row: R.main }
      : { id: 'expand', slot: 'retrieve' as Slot, title: 'Query expansion', sub: qe.replace('_', ' '), col: expandCol, row: R.main }] : []),
    { id: 'path-dense', slot: 'retrieve', title: 'Dense search', sub: s(cfg.vector_store.type), col: pathsCol, row: R.main - 1, off: !active.includes('dense') },
    { id: 'path-keyword', slot: 'retrieve', title: 'Keyword search', sub: 'BM25 · SQLite FTS5', col: pathsCol, row: R.main, off: !active.includes('keyword') },
    { id: 'path-exact', slot: 'retrieve', title: 'Exact lookup', sub: 'Errors · code symbols', col: pathsCol, row: R.main + 1, off: !active.includes('exact') },
    ...(showFuse ? [{ id: 'fuse', slot: 'retrieve' as Slot, title: 'Fuse & rank', sub: `${s(rt.fusion).toUpperCase()} · top ${s(rt.top_k)}${rt.mmr ? ' · MMR' : ''}${rt.okf_policy ? ' · OKF' : ''}`, col: fuseCol, row: R.main }] : []),
    { id: 'rerank', slot: 'rerank', title: 'Rerank', sub: cfg.rerank.type === 'none' ? 'Off' : `${s(cfg.rerank.type).replace('_', ' ')} · keep ${s(cfg.rerank.top_n)}`, col: rerankCol, row: R.main, off: cfg.rerank.type === 'none' },
    { id: 'prompt', slot: 'prompt', title: 'Prompt', sub: `${s(cfg.prompt.type).replace('_', ' ')} · ${s(cfg.prompt.max_context_tokens)} tokens`, col: rerankCol, row: R.answer },
    { id: 'generate', slot: 'generate', title: 'Generate', sub: s(cfg.generate.model) || s(cfg.generate.type), col: rerankCol - 1, row: R.answer },
    { id: 'verify', slot: 'verify', title: 'Verify', sub: verify.type === 'grounding_check' ? 'Grounding check' : verify.validate_output ? 'Output validation' : 'Off', col: rerankCol - 2, row: R.answer, off: !verifyOn },
    { id: 'answer', title: 'Answer', sub: 'With citations', col: rerankCol - 3, row: R.answer, io: true },
    { id: 'parse', slot: 'parse', title: 'Parse', sub: s(cfg.parse.type), col: 0, row: R.index },
    { id: 'chunk', slot: 'chunk', title: 'Chunk', sub: `${s(cfg.chunk.type).replace('_', ' ')} · ${s(cfg.chunk.size)}`, col: 1, row: R.index },
    { id: 'embed', slot: 'embed', title: 'Embed', sub: dense ? s(cfg.embed.model) || s(cfg.embed.type) : 'Not used by keyword retrieval', col: 2, row: R.index, off: !dense },
    { id: 'vector_store', slot: 'vector_store', title: 'Vector store', sub: dense ? s(cfg.vector_store.type) : 'Not used by keyword retrieval', col: 3, row: R.index, off: !dense },
  ]
  const flow = (ids: string[]): GEdge[] => ids.slice(1).map((to, i) => ({ from: ids[i], to }))
  const before = ['question', 'cache', 'compute', ...(showExpand ? ['expand'] : [])]
  const after = showFuse ? 'fuse' : 'rerank'
  const edges: GEdge[] = [
    ...flow(before),
    ...PATHS.map((p) => ({ from: before[before.length - 1], to: `path-${p}` })),
    ...PATHS.map((p) => ({ from: `path-${p}`, to: after })),
    ...(showFuse ? [{ from: 'fuse', to: 'rerank' }] : []),
    ...flow(['rerank', 'prompt', 'generate', 'verify', 'answer']),
    ...flow(['parse', 'chunk', 'embed', 'vector_store']),
    { from: 'vector_store', to: 'path-dense', label: 'vectors', kind: 'index' as const },
    { from: 'chunk', to: 'path-keyword', label: 'text', kind: 'index' as const },
    { from: 'chunk', to: 'path-exact', label: 'keys', kind: 'index' as const },
  ]
  if (cacheOn) edges.push({ from: 'cache', to: 'answer', label: 'cache hit', kind: 'branch' })
  if (computeOn) edges.push({ from: 'compute', to: 'answer', label: 'attested answer', kind: 'branch' })
  if (agentic) edges.push({ from: after, to: 'expand', label: 'search again', kind: 'branch' })
  if (verify.type === 'grounding_check' && verify.on_fail === 'retry_with_more_context' && Number(verify.max_retries) > 0) {
    edges.push({ from: 'verify', to: after, label: 'retry with more context', kind: 'branch' })
  }
  return { nodes, edges }
}

/** Which node a recorded trace step lights up (the query embedding belongs to dense search). */
export const STEP_NODE: Record<TraceStepName, string> = {
  query_expansion: 'expand', agent: 'expand', cache_lookup: 'cache', compute_route: 'compute', compute: 'compute', execution: 'compute',
  embed_query: 'path-dense', dense_search: 'path-dense', keyword_search: 'path-keyword', exact_search: 'path-exact',
  fuse: 'fuse', pin: 'fuse', mmr: 'fuse', okf_policy: 'fuse', rerank: 'rerank', context_window: 'prompt', prompt: 'prompt',
  generate: 'generate', verify: 'verify', output_validation: 'verify',
}

/** A test question as it runs: time per finished node, plus what the stream said is happening now. */
export interface Live {
  phase: 'running' | 'done' | 'error'
  ms: Record<string, number>
  /** The cache (or an attested computation) answered, so retrieval and generation are skipped. */
  skip: boolean
  generating: boolean
  verifying: boolean
  answer: string
  totalMs?: number
  error?: string
}
export const newLive = (): Live => ({ phase: 'running', ms: {}, skip: false, generating: false, verifying: false, answer: '' })

function fromTrace(l: Live, trace: TraceStep[]): Live {
  const ms: Record<string, number> = {}
  let skip = false
  for (const st of trace) {
    ms[STEP_NODE[st.step]] = (ms[STEP_NODE[st.step]] ?? 0) + st.ms
    if (st.step === 'cache_lookup' && st.payload.hit) skip = true
    if (st.step === 'compute' && st.payload.attested) skip = true
  }
  return { ...l, ms, skip }
}

export function reduceLive(l: Live, ev: ChatEvent): Live {
  switch (ev.type) {
    case 'step': {
      if (ev.step === 'embed_query') return l // dense search isn't finished until its own step lands
      const id = STEP_NODE[ev.step]
      return { ...l, ms: { ...l.ms, [id]: (l.ms[id] ?? 0) + ev.ms }, skip: l.skip || (ev.step === 'cache_lookup' && !!ev.hit) }
    }
    case 'retrieval': {
      const n = fromTrace(l, ev.trace)
      return { ...n, generating: !n.skip }
    }
    case 'token': return { ...l, answer: l.answer + ev.text, generating: !l.skip && !l.verifying }
    case 'verifying': return { ...l, verifying: true, generating: false }
    case 'verify': case 'execution': return { ...l, verifying: false }
    case 'retry': return { ...l, ms: {}, answer: '', generating: false, verifying: false }
    case 'done': return { ...fromTrace(l, ev.trace), phase: 'done', generating: false, verifying: false, answer: ev.answer, totalMs: ev.totals.ms }
    case 'error': return { ...l, phase: 'error', generating: false, verifying: false, error: ev.message }
    default: return l
  }
}

const LANE = [['cache'], ['compute'], ['expand'], ['path-dense', 'path-keyword', 'path-exact'], ['fuse'], ['rerank'], ['prompt']]
/** Nodes working right now. Steps report when they finish, so the running ones are the next enabled stage(s) in
 *  pipeline order that haven't finished and have nothing after them finished yet. */
export function runningNodes(l: Live | null, isOn: (id: string) => boolean): Set<string> {
  if (!l || l.phase !== 'running' || l.skip) return new Set()
  if (l.verifying) return new Set(['verify'])
  if (l.generating) return new Set(['generate'])
  for (let i = 0; i < LANE.length; i++) {
    const pending = LANE[i].filter((id) => isOn(id) && !(id in l.ms))
    if (pending.length && !LANE.slice(i + 1).some((g) => g.some((id) => id in l.ms))) return new Set(pending)
  }
  return new Set(['prompt'])
}

// ---- layout geometry ---------------------------------------------------------------------------------------------
// Pure, so it can be checked without a browser (see `scripts/check-canvas.ts`).

/** Node geometry at 100% zoom: 13 px titles and 12 px detail lines, so the diagram reads without zooming. */
export const W = 188, H = 64, COL = 216, ROW = 90, PAD = 24, TOP = 24
export type Pt = [number, number]

export const nodePos = (n: GNode) => ({ x: PAD + n.col * COL, y: PAD + TOP + n.row * ROW })

/** One axis-aligned polyline per edge. Forward flow runs side to side (or straight down/up within a column);
 *  branches and index feeds get their own channels (the empty rows between the lanes) so no line crosses a step. */
export function routeEdges(nodes: GNode[], edges: GEdge[]): Pt[][] {
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const branches = edges.filter((e) => e.kind === 'branch')
  const indexes = edges.filter((e) => e.kind === 'index')
  const chanY = PAD + TOP + 4 * ROW + H / 2
  /** Where a branch meets a node's top or bottom. Every branch end in a column gets its own x, so lines in one column
   *  never merge; the column holding Rerank (whose bottom already carries the flow down to Prompt) uses its left quarter. */
  const ends = (col: number) => branches.flatMap((x, i) => [[i, 'from', byId[x.from]], [i, 'to', byId[x.to]]] as const).filter((t) => t[2].col === col)
  const branchX = (n: GNode, e: GEdge, side: 'from' | 'to') => {
    const list = ends(n.col), i = list.findIndex((t) => t[0] === branches.indexOf(e) && t[1] === side), cnt = list.length
    const vertical = nodes.some((m) => m.id === 'rerank' && m.col === n.col)
    const lo = vertical ? 0.08 : 0.2, hi = vertical ? 0.38 : 0.8
    const f = cnt === 1 ? (vertical ? 0.22 : 0.5) : lo + ((hi - lo) * i) / (cnt - 1)
    return nodePos(n).x + W * f
  }
  return edges.map((e): Pt[] => {
    const a = byId[e.from], b = byId[e.to], pa = nodePos(a), pb = nodePos(b)
    if (e.kind === 'branch') {
      const y = chanY + (branches.indexOf(e) - (branches.length - 1) / 2) * 8
      const sx = branchX(a, e, 'from'), tx = branchX(b, e, 'to')
      const sy = a.row < 4 ? pa.y + H : pa.y, ty = b.row < 4 ? pb.y + H : pb.y
      return [[sx, sy], [sx, y], [tx, y], [tx, ty]]
    }
    if (e.kind === 'index') {
      if (a.col === b.col) return [[pa.x + W / 2, pa.y + H], [pb.x + W / 2, pb.y]]
      const k = indexes.indexOf(e)
      // Feeds from one step fan out along its bottom, and enter the target's left side above the flow edge's entry point.
      const sib = indexes.filter((x) => x.from === e.from), sx = pa.x + W / 2 + (sib.indexOf(e) - (sib.length - 1) / 2) * 12
      const yc = pa.y + H + 9 + k * 5, gx = pb.x - 16 - k * 5, ty = pb.y + 12
      return [[sx, pa.y + H], [sx, yc], [gx, yc], [gx, ty], [pb.x, ty]]
    }
    if (a.col === b.col) {
      return a.row < b.row ? [[pa.x + W / 2, pa.y + H], [pb.x + W / 2, pb.y]] : [[pa.x + W / 2, pa.y], [pb.x + W / 2, pb.y + H]]
    }
    const right = b.col > a.col
    const x1 = right ? pa.x + W : pa.x, y1 = pa.y + H / 2, x2 = right ? pb.x : pb.x + W, y2 = pb.y + H / 2
    if (y1 === y2) return [[x1, y1], [x2, y2]]
    const mx = right ? x2 - 8 : x2 + 8 // the bend sits just before the target, leaving the gutter's left side to index feeds
    return [[x1, y1], [mx, y1], [mx, y2], [x2, y2]]
  })
}

/** SVG path through the points, with softly rounded corners. */
export function toPath(pts: Pt[], r = 10): string {
  let d = `M${pts[0][0]},${pts[0][1]}`
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1], [x, y] = pts[i], [nx, ny] = pts[i + 1]
    const a = Math.min(r, Math.hypot(x - px, y - py) / 2), b = Math.min(r, Math.hypot(nx - x, ny - y) / 2)
    d += ` L${x - Math.sign(x - px) * a},${y - Math.sign(y - py) * a} Q${x},${y} ${x + Math.sign(nx - x) * b},${y + Math.sign(ny - y) * b}`
  }
  const [lx, ly] = pts[pts.length - 1]
  return `${d} L${lx},${ly}`
}
