// Checks the Canvas layout across pipeline shapes: nodes never overlap, no edge runs through a step it doesn't
// connect, edges start and end on node borders, and branches never share a stretch of line.
// Run: node scripts/check-canvas.ts
import { H, W, buildGraph, nodePos, routeEdges, type GNode, type Pt } from '../src/features/configure/Canvas.utils.ts'

const cfgs: Record<string, unknown>[] = []
const retrieves = [
  { type: 'fused' }, { type: 'hybrid' }, { type: 'dense' }, { type: 'keyword' }, { type: 'dense', mmr: true },
  ...['fused', 'hybrid', 'dense', 'keyword'].map((search_mode) => ({ type: 'agentic', search_mode, max_steps: 3 })),
]
for (const r of retrieves) for (const qe of ['none', 'multi_query']) for (const cache of ['none', 'semantic'])
  for (const compute of ['none', 'attested']) for (const verify of [{ type: 'none' }, { type: 'grounding_check', on_fail: 'retry_with_more_context', max_retries: 1 }, { type: 'grounding_check', on_fail: 'flag', max_retries: 0 }, { type: 'none', validate_output: true }])
    for (const rerank of ['none', 'cross_encoder'])
      cfgs.push({
        parse: { type: 'pymupdf4llm' }, chunk: { type: 'structure_aware', size: 700 }, embed: { type: 'fastembed', model: 'bge' }, vector_store: { type: 'faiss' },
        retrieve: { top_k: 8, fusion: 'rrf', query_expansion: qe, ...r }, cache: { type: cache, threshold: 0.95 }, compute: { type: compute },
        rerank: { type: rerank, top_n: 5 }, prompt: { type: 'cited_qa', max_context_tokens: 4000 }, generate: { type: 'gemini' }, verify,
      })

const inside = (p: Pt, n: GNode, m: number) => {
  const q = nodePos(n)
  return p[0] > q.x + m && p[0] < q.x + W - m && p[1] > q.y + m && p[1] < q.y + H - m
}
const onBorder = (p: Pt, n: GNode) => {
  const q = nodePos(n), e = 0.5
  const inX = p[0] >= q.x - e && p[0] <= q.x + W + e, inY = p[1] >= q.y - e && p[1] <= q.y + H + e
  return inX && inY && (Math.abs(p[0] - q.x) < e || Math.abs(p[0] - q.x - W) < e || Math.abs(p[1] - q.y) < e || Math.abs(p[1] - q.y - H) < e)
}
/** Does the axis-aligned segment pass through the interior of the node? */
const crosses = (a: Pt, b: Pt, n: GNode) => {
  const q = nodePos(n), m = 1
  const x0 = Math.min(a[0], b[0]), x1 = Math.max(a[0], b[0]), y0 = Math.min(a[1], b[1]), y1 = Math.max(a[1], b[1])
  return x1 > q.x + m && x0 < q.x + W - m && y1 > q.y + m && y0 < q.y + H - m
}

// the checker itself must notice a line through a step
{
  const n = buildGraph(cfgs[0] as never).nodes[0], q = nodePos(n)
  if (!crosses([q.x - 10, q.y + H / 2], [q.x + W + 10, q.y + H / 2], n)) throw new Error('crosses() is blind')
  if (crosses([q.x - 10, q.y - 5], [q.x + W + 10, q.y - 5], n)) throw new Error('crosses() is too eager')
}

let bad = 0
const fail = (cfg: number, msg: string) => { if (bad++ < 25) console.log(`#${cfg}: ${msg}`) }
cfgs.forEach((cfg, ci) => {
  const { nodes, edges } = buildGraph(cfg as never)
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const tag = JSON.stringify({ r: (cfg.retrieve as { type: string; search_mode?: string; query_expansion: string }), c: (cfg.cache as { type: string }).type, k: (cfg.compute as { type: string }).type, v: (cfg.verify as { type: string }).type })
  for (const n of nodes) if (n.col < 0) fail(ci, `${n.id} has negative column ${tag}`)
  for (const a of nodes) for (const b of nodes) if (a.id < b.id) {
    const p = nodePos(a), q = nodePos(b)
    if (p.x < q.x + W + 4 && q.x < p.x + W + 4 && p.y < q.y + H + 4 && q.y < p.y + H + 4) fail(ci, `${a.id} overlaps ${b.id} ${tag}`)
  }
  const routes = routeEdges(nodes, edges)
  const branchSegs: { e: number; a: Pt; b: Pt }[] = []
  edges.forEach((e, i) => {
    const r = routes[i], a = byId[e.from], b = byId[e.to]
    if (!onBorder(r[0], a)) fail(ci, `edge ${e.from}→${e.to} starts off ${a.id}'s border ${tag}`)
    if (!onBorder(r[r.length - 1], b)) fail(ci, `edge ${e.from}→${e.to} ends off ${b.id}'s border ${tag}`)
    for (let s = 0; s + 1 < r.length; s++) {
      if (r[s][0] !== r[s + 1][0] && r[s][1] !== r[s + 1][1]) fail(ci, `edge ${e.from}→${e.to} has a diagonal segment ${tag}`)
      for (const n of nodes) if (crosses(r[s], r[s + 1], n)) fail(ci, `edge ${e.from}→${e.to} runs through ${n.id} ${tag}`)
      if (e.kind === 'branch') branchSegs.push({ e: i, a: r[s], b: r[s + 1] })
    }
    if (inside(r[0], b, 1) || inside(r[r.length - 1], a, 1)) fail(ci, `edge ${e.from}→${e.to} ends inside the wrong node ${tag}`)
  })
  // a branch or index feed must never lie on top of another edge (fan-in/fan-out buses of plain flow edges may share)
  const segs = edges.flatMap((e, i) => routes[i].slice(0, -1).map((p, k) => ({ i, e, a: p, b: routes[i][k + 1] })))
  for (const s of segs) for (const t of segs) if (s.i < t.i && (s.e.kind || t.e.kind)) {
    const sv = s.a[0] === s.b[0], tv = t.a[0] === t.b[0]
    const [s0, s1] = sv ? [Math.min(s.a[1], s.b[1]), Math.max(s.a[1], s.b[1])] : [Math.min(s.a[0], s.b[0]), Math.max(s.a[0], s.b[0])]
    const [t0, t1] = tv ? [Math.min(t.a[1], t.b[1]), Math.max(t.a[1], t.b[1])] : [Math.min(t.a[0], t.b[0]), Math.max(t.a[0], t.b[0])]
    const same = sv === tv && (sv ? s.a[0] === t.a[0] : s.a[1] === t.a[1])
    if (same && Math.min(s1, t1) - Math.max(s0, t0) > 0.5) fail(ci, `${s.e.from}→${s.e.to} overlaps ${t.e.from}→${t.e.to} ${tag}`)
  }
})
console.log(`${cfgs.length} configurations checked, ${bad} problem${bad === 1 ? '' : 's'}`)
process.exit(bad ? 1 : 0)
