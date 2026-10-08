import { useMemo, useRef, useState, type DragEvent, type PointerEvent as RPointerEvent } from 'react'
import { LayoutGrid, X } from 'lucide-react'
import type { Change, NodeConfig, PipelineConfig, PipelineFieldError, Slot, SlotCatalog } from '@/api/types'
import { Badge, Button, cn, useToast } from '@/components/ui'
import { StageCard } from './ConfigEditor'
import { PATHS, buildGraph, modeFor, type GNode, type Path } from './Canvas.utils'

const W = 168, H = 60, COL = 184, ROW = 84, PAD = 24
const DND = 'application/x-raglabs-node-type'

type Pos = Record<string, { x: number; y: number }>

function loadLayout(projectId: string): Pos {
  try {
    return JSON.parse(localStorage.getItem(`raglabs.canvas.${projectId}`) ?? '{}') as Pos
  } catch {
    return {}
  }
}
function saveLayout(projectId: string, pos: Pos) {
  try {
    localStorage.setItem(`raglabs.canvas.${projectId}`, JSON.stringify(pos))
  } catch {
    // private mode / blocked storage: the layout just isn't remembered
  }
}

interface CanvasProps {
  projectId: string
  value: PipelineConfig
  onChange: (c: PipelineConfig) => void
  baseline?: PipelineConfig
  catalog: SlotCatalog[]
  errors?: PipelineFieldError[]
  changedBySlot: Map<Slot, Change[]>
}

/** FR-3.24: the pipeline as its real execution graph — drag nodes, drop a type onto a slot, toggle
 *  retrieval paths, click a node to edit it. Edits the same draft as the form view. */
export function Canvas({ projectId, value, onChange, baseline, catalog, errors, changedBySlot }: CanvasProps) {
  const { toast } = useToast()
  const { nodes, edges } = useMemo(() => buildGraph(value), [value])
  const [layout, setLayout] = useState<Pos>(() => loadLayout(projectId))
  const [selected, setSelected] = useState<Slot | null>(null)
  const [dropOn, setDropOn] = useState<string | null>(null)
  const drag = useRef<{ id: string; dx: number; dy: number; moved: boolean } | null>(null)
  const pos = (n: GNode) => layout[n.id] ?? { x: PAD + n.col * COL, y: PAD + n.row * ROW }
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const width = PAD * 2 + 11 * COL, height = PAD * 2 + 6 * ROW
  const slotCat = (slot?: Slot) => catalog.find((c) => c.slot === slot)

  const setType = (slot: Slot, type: string) => {
    const t = slotCat(slot)?.types.find((x) => x.type === type)
    if (!t || !t.available || value[slot]?.type === type) return
    onChange({ ...value, [slot]: { ...t.defaults, type } as NodeConfig })
    toast({ tone: 'success', title: `${slotCat(slot)?.title ?? slot}: ${t.title}` })
  }

  const togglePath = (p: Path) => {
    const rt = value.retrieve as Record<string, unknown>
    const field = rt.type === 'agentic' ? 'search_mode' : 'type'
    const cur = PATHS.filter((x) => !byId[`path-${x}`].off)
    const next = cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]
    const mode = modeFor(next)
    if (!mode) {
      toast({ tone: 'warning', title: "No retriever runs that combination",
        description: 'Exact lookup runs together with dense + keyword (Fused); at least one path must stay on.' })
      return
    }
    if (field === 'type') {
      const t = slotCat('retrieve')?.types.find((x) => x.type === mode)
      onChange({ ...value, retrieve: { ...(t?.defaults ?? {}), ...rt, type: mode } as NodeConfig })
    } else onChange({ ...value, retrieve: { ...value.retrieve, search_mode: mode } })
  }

  const onPointerDown = (e: RPointerEvent, n: GNode) => {
    if ((e.target as HTMLElement).closest('[data-no-drag]')) return
    const p = pos(n)
    drag.current = { id: n.id, dx: e.clientX - p.x, dy: e.clientY - p.y, moved: false }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: RPointerEvent) => {
    const d = drag.current
    if (!d) return
    const x = Math.max(0, Math.min(width - W, e.clientX - d.dx)), y = Math.max(0, Math.min(height - H, e.clientY - d.dy))
    const cur = layout[d.id] ?? pos(byId[d.id])
    if (!d.moved && Math.hypot(x - cur.x, y - cur.y) < 4) return
    d.moved = true
    setLayout((l) => ({ ...l, [d.id]: { x, y } }))
  }
  const onPointerUp = (n: GNode) => {
    const d = drag.current
    drag.current = null
    if (d?.moved) saveLayout(projectId, layout)
    else if (n.slot) setSelected(n.slot)
  }

  // Branches get their own lanes so they never cross nodes: forward exits run along the empty row between
  // the query and index lanes, loops along the empty top row.
  const LOW = PAD + 4 * ROW + H / 2, HIGH = PAD + H / 2 - 12
  const branchIdx = (a: GNode, b: GNode) => edges.filter((e) => e.kind === 'branch').findIndex((e) => e.from === a.id && e.to === b.id)
  const lane = (a: GNode, b: GNode) => (pos(b).x < pos(a).x ? HIGH - branchIdx(a, b) * 6 : LOW + branchIdx(a, b) * 16)
  const edgePath = (a: GNode, b: GNode, branch: boolean) => {
    const pa = pos(a), pb = pos(b)
    if (branch) {
      const y = lane(a, b), up = y < pa.y
      const sx = pa.x + W / 2, sy = up ? pa.y : pa.y + H, tx = pb.x + W / 2, ty = up ? pb.y : pb.y + H
      const dir = tx > sx ? 1 : -1
      return `M${sx},${sy} C${sx},${y} ${sx},${y} ${sx + 24 * dir},${y} L${tx - 24 * dir},${y} C${tx},${y} ${tx},${y} ${tx},${ty}`
    }
    const x1 = pa.x + W, y1 = pa.y + H / 2, x2 = pb.x, y2 = pb.y + H / 2
    const mx = (x1 + x2) / 2
    return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`
  }

  const sel = selected ? slotCat(selected) : undefined
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-body-sm text-text-secondary">
        <span>Drag a type onto its node to switch it ·</span>
        {catalog.filter((c) => c.types.length > 1).map((c) => (
          <span key={c.slot} className="flex flex-wrap items-center gap-1">
            <span className="text-text-tertiary">{c.title}:</span>
            {c.types.filter((t) => t.available).map((t) => (
              <span key={t.type} draggable onDragStart={(e: DragEvent) => e.dataTransfer.setData(DND, `${c.slot}:${t.type}`)}
                title={t.description}
                className={cn('cursor-grab rounded-full border px-2 py-0.5 text-caption',
                  value[c.slot]?.type === t.type ? 'border-accent-default bg-accent-subtle text-accent-text' : 'border-border-default bg-bg-surface')}>
                {t.title}
              </span>
            ))}
          </span>
        ))}
        <Button size="sm" variant="ghost" className="ml-auto" icon={<LayoutGrid size={12} aria-hidden />}
          onClick={() => { setLayout({}); saveLayout(projectId, {}) }}>
          Reset layout
        </Button>
      </div>

      <div className="flex items-start gap-3">
      <div className="relative min-w-0 flex-1 overflow-auto rounded-lg border border-border-default bg-bg-subtle" style={{ maxHeight: 640 }}>
        <div className="relative" style={{ width, height }} onPointerMove={onPointerMove}>
          <svg width={width} height={height} className="pointer-events-none absolute inset-0" aria-hidden>
            <defs>
              <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L8,4 L0,8 z" className="fill-text-tertiary" />
              </marker>
            </defs>
            {edges.map((e, i) => {
              const a = byId[e.from], b = byId[e.to]
              const muted = a.off || b.off
              const d = edgePath(a, b, e.kind === 'branch')
              const pa = pos(a), pb = pos(b)
              return (
                <g key={i}>
                  <path d={d} fill="none" markerEnd="url(#arrow)" strokeWidth={e.kind === 'branch' ? 2 : 1.5}
                    strokeDasharray={e.kind === 'index' ? '2 4' : e.kind === 'branch' ? '6 4' : undefined}
                    className={cn(e.kind === 'branch' ? 'stroke-accent-default' : 'stroke-text-tertiary', muted && 'opacity-30')} />
                  {e.label && (
                    <text x={(pa.x + pb.x + W) / 2} y={e.kind === 'branch' ? lane(a, b) - 6 : (pa.y + pb.y + H) / 2 - 4}
                      textAnchor="middle" className={cn('text-[11px]', e.kind === 'branch' ? 'fill-accent-text' : 'fill-text-tertiary')}>
                      {e.label}
                    </text>
                  )}
                </g>
              )
            })}
          </svg>
          {nodes.map((n) => {
            const p = pos(n)
            const path = n.id.startsWith('path-') ? (n.id.slice(5) as Path) : null
            const changed = n.slot && changedBySlot.get(n.slot)?.length
            const hasErr = n.slot && errors?.some((e) => e.slot === n.slot)
            return (
              <div
                key={n.id}
                id={n.slot && !path && n.id !== 'expand' && n.id !== 'fuse' ? `canvas-${n.slot}` : n.id === 'fuse' ? 'canvas-retrieve' : undefined}
                role={n.slot ? 'button' : undefined}
                tabIndex={n.slot ? 0 : -1}
                aria-label={n.slot ? `${n.title}: ${n.sub}. Edit` : `${n.title}: ${n.sub}`}
                onKeyDown={(e) => { if (n.slot && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setSelected(n.slot) } }}
                onPointerDown={(e) => onPointerDown(e, n)}
                onPointerUp={() => onPointerUp(n)}
                onDragOver={(e) => { if (n.slot && e.dataTransfer.types.includes(DND)) { e.preventDefault(); setDropOn(n.id) } }}
                onDragLeave={() => setDropOn(null)}
                onDrop={(e) => {
                  setDropOn(null)
                  const [slot, type] = e.dataTransfer.getData(DND).split(':')
                  if (n.slot && slot === n.slot) setType(n.slot, type)
                  else if (slot) toast({ tone: 'warning', title: `That's a ${slot.replace('_', ' ')} type — drop it on the ${slot.replace('_', ' ')} node.` })
                }}
                className={cn(
                  'focus-ring absolute flex touch-none select-none flex-col justify-center rounded-lg border px-3 shadow-sm transition-[opacity,box-shadow]',
                  n.io ? 'border-border-strong bg-bg-muted' : 'cursor-grab border-border-default bg-bg-surface active:cursor-grabbing',
                  n.off && 'border-dashed opacity-50',
                  selected && n.slot === selected && 'ring-2 ring-accent-default',
                  dropOn === n.id && 'ring-2 ring-accent-default ring-offset-2',
                  hasErr && 'border-danger-fg',
                )}
                style={{ left: p.x, top: p.y, width: W, height: H }}
              >
                <span className="flex items-center gap-1.5 truncate text-label text-text-primary">
                  {path && (
                    <input type="checkbox" data-no-drag checked={!n.off} onChange={() => togglePath(path)} aria-label={`${n.title} on`}
                      onClick={(e) => e.stopPropagation()} className="size-3.5 accent-[var(--color-accent-default)]" />
                  )}
                  {n.title}
                  {changed ? <span aria-label="changed" className="ml-auto size-2 shrink-0 rounded-full bg-accent-default" /> : null}
                </span>
                <span className="truncate font-mono text-mono-sm text-text-tertiary">{n.sub}</span>
              </div>
            )
          })}
        </div>
      </div>

        {sel && selected && (
          <aside className="max-h-[640px] w-[480px] shrink-0 overflow-y-auto rounded-lg border border-border-default bg-bg-surface p-4 shadow-lg" aria-label={`${sel.title} settings`}>
            <div className="mb-2 flex items-center gap-2">
              <Badge tone="neutral">{sel.title}</Badge>
              <Button size="sm" variant="ghost" className="ml-auto" iconOnly aria-label="Close" icon={<X size={14} aria-hidden />} onClick={() => setSelected(null)} />
            </div>
            <StageCard n={catalog.indexOf(sel) + 1} slot={selected} catalog={sel} value={value[selected]} baseline={baseline?.[selected]}
              changes={changedBySlot.get(selected)} errors={errors} projectId={projectId}
              onChange={(c) => onChange({ ...value, [selected]: c })} />
          </aside>
        )}
      </div>
      <p className="text-body-sm text-text-tertiary">
        The graph is how a question actually runs: dashed accent lines are early exits and loops (cache hit, attested computation,
        the agent's search loop, the grounding check's retry); dotted lines are what the index feeds each search. Steps run in this
        order — RAGLabs doesn't rewire them into arbitrary graphs, so every configuration stays comparable on the leaderboard.
      </p>
    </div>
  )
}
