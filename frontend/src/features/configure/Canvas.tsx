import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as RPointerEvent } from 'react'
import { Check, CircleHelp, Maximize, Play, X, ZoomIn, ZoomOut } from 'lucide-react'
import { errorMessage, streamChat } from '@/api/hooks'
import type { Change, NodeConfig, PipelineConfig, PipelineFieldError, Slot, SlotCatalog } from '@/api/types'
import { Button, Spinner, cn, useToast } from '@/components/ui'
import { StageCard } from './ConfigEditor'
import { deepEqual } from './schema'
import { H, PAD, PATHS, W, buildGraph, modeFor, newLive, nodePos, reduceLive, routeEdges, runningNodes, toPath, type GNode, type Live, type Path, type Pt } from './Canvas.utils'

// Node geometry at 100% zoom: 13 px titles and 12 px detail lines, so the diagram reads without zooming.
const PANEL = 380
const MIN_K = 0.3, MAX_K = 2

/** One hue per stage family — the same tokens colour the step list in the form view. */
const FAMILY = { gate: 'var(--color-fam-gate)', retrieve: 'var(--color-fam-retrieve)', generate: 'var(--color-fam-generate)', index: 'var(--color-fam-index)', io: 'var(--color-fam-io)' }
const familyOf = (id: string): keyof typeof FAMILY =>
  ['parse', 'chunk', 'embed', 'vector_store'].includes(id) ? 'index'
    : ['prompt', 'generate', 'verify'].includes(id) ? 'generate'
    : id === 'cache' || id === 'compute' ? 'gate' : id === 'question' || id === 'answer' ? 'io' : 'retrieve'
/** Slots whose whole stage can be switched off with type "none". */
const TOGGLE_SLOTS: Slot[] = ['cache', 'compute', 'rerank', 'verify']

type View = { x: number; y: number; k: number }
/** A press on the canvas: pans once it moves; if it never moves it's a click on `id` (or on empty space). */
type Gesture = { id?: string; sx: number; sy: number; vx: number; vy: number; moved: boolean }

const clampK = (k: number) => Math.max(MIN_K, Math.min(MAX_K, k))

interface CanvasProps {
  projectId: string
  value: PipelineConfig
  onChange: (c: PipelineConfig) => void
  baseline?: PipelineConfig
  catalog: SlotCatalog[]
  errors?: PipelineFieldError[]
  changedBySlot: Map<Slot, Change[]>
}

/** FR-3.24: the pipeline as its real execution graph — pan/zoom, toggle steps, click a step to edit it in a side
 *  panel that sits next to the graph (the graph re-fits to the space left). Edits the same draft as the form view. */
export function Canvas({ projectId, value, onChange, baseline, catalog, errors, changedBySlot }: CanvasProps) {
  const { toast } = useToast()
  const { nodes, edges } = useMemo(() => {
    const g = buildGraph(value)
    // Show the name the picker shows (e.g. "GLM 5.3"), not the raw provider id, when no model is set.
    for (const n of g.nodes) {
      const cfg = n.slot ? (value[n.slot] as Record<string, unknown> | undefined) : undefined
      const t = n.slot && !n.id.startsWith('path-') && n.id !== 'fuse' && n.id !== 'expand' && !cfg?.model
        ? catalog.find((c) => c.slot === n.slot)?.types.find((x) => x.type === cfg?.type)?.title : undefined
      if (t && (n.slot === 'generate' || (n.slot === 'embed' && !n.off))) n.sub = t
    }
    return g
  }, [value, catalog])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 })
  const [hoverEdge, setHoverEdge] = useState<number | null>(null)
  const [question, setQuestion] = useState('')
  const [live, setLive] = useState<Live | null>(null)
  const abort = useRef<AbortController | null>(null)
  const askQuestion = async () => {
    const q = question.trim()
    if (!q || live?.phase === 'running') return
    abort.current?.abort()
    const ctl = (abort.current = new AbortController())
    setLive(newLive())
    try {
      await streamChat(projectId, { question: q }, { signal: ctl.signal, onEvent: (ev) => setLive((l) => (l ? reduceLive(l, ev) : l)) })
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') setLive((l) => (l ? { ...l, phase: 'error', error: errorMessage(e) } : l))
    }
    setLive((l) => (l && l.phase === 'running' ? { ...l, phase: 'done' } : l))
  }
  const stopOrClear = () => { abort.current?.abort(); setLive(null) }
  const frame = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const gesture = useRef<Gesture | null>(null)
  const touched = useRef(false) // once the user pans/zooms, stop auto-fitting on resize
  const pos = nodePos
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const slotCat = (slot?: Slot) => catalog.find((c) => c.slot === slot)
  const selectedNode = selectedId ? byId[selectedId] : undefined
  const selected = selectedNode?.slot ?? null
  const sel = selected ? slotCat(selected) : undefined

  const ps = nodes.map(pos)
  const bounds = {
    x0: Math.min(...ps.map((p) => p.x)) - PAD, x1: Math.max(...ps.map((p) => p.x)) + W + PAD,
    y0: 0, y1: Math.max(...ps.map((p) => p.y)) + H + PAD,
  }
  const boundsRef = useRef(bounds)
  boundsRef.current = bounds
  const width = bounds.x1, height = bounds.y1
  const fit = () => {
    const r = box.current?.getBoundingClientRect()
    if (!r || !r.width) return
    const b = boundsRef.current, bw = b.x1 - b.x0, bh = b.y1 - b.y0
    const k = clampK(Math.min((r.width - 16) / bw, (r.height - 16) / bh, 1))
    setView({ k, x: (r.width - bw * k) / 2 - b.x0 * k, y: (r.height - bh * k) / 2 - b.y0 * k })
  }
  useLayoutEffect(() => {
    frame.current?.scrollIntoView({ block: 'start' })
    fit()
    const ro = new ResizeObserver(() => { if (!touched.current) fit() })
    if (box.current) ro.observe(box.current)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // The side panel takes width from the graph, so re-fit when it opens or closes (and when the graph's shape changes).
  const shape = `${bounds.x1}x${bounds.y1}`
  useEffect(() => {
    const id = requestAnimationFrame(() => { if (!touched.current) fit() })
    return () => cancelAnimationFrame(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!sel, shape])

  const zoomAt = (cx: number, cy: number, factor: number) => {
    touched.current = true
    setView((v) => {
      const k = clampK(v.k * factor)
      return { k, x: cx - ((cx - v.x) * k) / v.k, y: cy - ((cy - v.y) * k) / v.k }
    })
  }
  const zoomCenter = (factor: number) => {
    const r = box.current?.getBoundingClientRect()
    if (r) zoomAt(r.width / 2, r.height / 2, factor)
  }
  // Wheel zoom needs a non-passive listener so it can stop the page from scrolling underneath.
  useEffect(() => {
    const el = viewport.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return // plain scroll belongs to the page; zoom needs Ctrl/⌘ (or a pinch)
      e.preventDefault()
      const r = el.getBoundingClientRect()
      zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

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

  const toggleStage = (slot: Slot, on: boolean) => {
    const types = slotCat(slot)?.types ?? []
    const t = on ? types.find((x) => x.type !== 'none' && x.available) : types.find((x) => x.type === 'none')
    if (!on) onChange({ ...value, [slot]: { ...(t?.defaults ?? {}), type: 'none' } as NodeConfig })
    else if (t) onChange({ ...value, [slot]: { ...t.defaults, type: t.type } as NodeConfig })
    else toast({ tone: 'warning', title: `No ${slotCat(slot)?.title.toLowerCase() ?? slot} option is available yet`, description: 'Connect a provider first.' })
  }

  const select = (n: GNode) => {
    if (!n.slot) return
    setSelectedId(n.id)
  }
  const closePanel = () => {
    const id = selectedId
    setSelectedId(null)
    if (id) box.current?.querySelector<HTMLElement>(`[data-node="${id}"]`)?.focus()
  }

  const onPointerDown = (e: RPointerEvent) => {
    const t = e.target as HTMLElement
    if (e.button !== 0 || t.closest('[data-no-drag]')) return
    gesture.current = { id: t.closest<HTMLElement>('[data-node]')?.dataset.node, sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y, moved: false }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: RPointerEvent) => {
    const g = gesture.current
    if (!g) return
    const mx = e.clientX - g.sx, my = e.clientY - g.sy
    if (!g.moved && Math.hypot(mx, my) < 4) return
    g.moved = true
    touched.current = true
    setView((v) => ({ ...v, x: g.vx + mx, y: g.vy + my }))
  }
  const onPointerUp = () => {
    const g = gesture.current
    gesture.current = null
    if (!g || g.moved) return
    if (g.id) select(byId[g.id])
    else setSelectedId(null)
  }

  /** Arrow keys hop to the nearest node in that direction; Enter/Space opens it. */
  const onNodeKey = (e: KeyboardEvent, n: GNode) => {
    if (e.key === 'Enter' || e.key === ' ') {
      if (!n.slot) return
      e.preventDefault()
      select(n)
      return
    }
    const dir = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] }[e.key]
    if (!dir) return
    e.preventDefault()
    const a = pos(n)
    let best: GNode | null = null, bestScore = Infinity
    for (const m of nodes) {
      if (m === n) continue
      const b = pos(m), dx = b.x - a.x, dy = b.y - a.y
      const along = dx * dir[0] + dy * dir[1], across = Math.abs(dx * dir[1] + dy * dir[0])
      if (along <= 0) continue
      const score = along + across * 2 // prefer nodes straight ahead over far diagonals
      if (score < bestScore) { best = m; bestScore = score }
    }
    if (best) box.current?.querySelector<HTMLElement>(`[data-node="${best.id}"]`)?.focus()
  }

  const routes = useMemo(() => routeEdges(nodes, edges), [nodes, edges])
  const drafted = !!baseline && !deepEqual(value, baseline)
  const running = runningNodes(live, (id) => !!byId[id] && !byId[id].off)
  const tabStop = focusId && byId[focusId] ? focusId : 'question'
  const hotLabel = hoverEdge !== null ? edges[hoverEdge] : null
  return (
    <div
      ref={frame}
      className="relative flex h-[calc(100dvh-var(--topbar-h)-5.5rem)] min-h-[480px] scroll-mt-[calc(var(--topbar-h)+8px)] overflow-hidden rounded-lg border border-border-default bg-bg-subtle"
      onKeyDown={(e) => { if (e.key === 'Escape' && selectedId) { e.stopPropagation(); closePanel() } }}
    >
      <div className="flex min-w-0 flex-1 flex-col">
      <div className="relative z-30 flex shrink-0 flex-wrap items-center gap-2 border-b border-border-default bg-bg-surface px-3 py-2">
        <form className="flex min-w-0 flex-1 items-center gap-1" onSubmit={(e) => { e.preventDefault(); void askQuestion() }}>
          <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Test a question on the active version…"
            aria-label="Test question" className="focus-ring min-w-0 max-w-[460px] flex-1 rounded border border-border-default bg-bg-surface px-2 py-1 text-body-sm text-text-primary placeholder:text-text-secondary" />
          <Button size="sm" type="submit" loading={live?.phase === 'running'} disabled={!question.trim()} icon={<Play size={12} aria-hidden />}>Run</Button>
          {live && <Button size="sm" variant="ghost" iconOnly aria-label={live.phase === 'running' ? 'Stop test run' : 'Clear test run'} icon={<X size={14} aria-hidden />} onClick={stopOrClear} />}
        </form>
        {drafted && <span className="text-caption text-warning-fg">Test runs use the active version, not this unsaved draft.</span>}
        <div className="flex items-center gap-1" role="toolbar" aria-label="Canvas controls">
          <Button size="sm" variant="ghost" iconOnly aria-label="Zoom out" icon={<ZoomOut size={14} aria-hidden />} onClick={() => zoomCenter(1 / 1.25)} />
          <span className="w-10 text-center text-caption tabular-nums text-text-secondary" aria-live="off">{Math.round(view.k * 100)}%</span>
          <Button size="sm" variant="ghost" iconOnly aria-label="Zoom in" icon={<ZoomIn size={14} aria-hidden />} onClick={() => zoomCenter(1.25)} />
          <Button size="sm" variant="ghost" iconOnly aria-label="Fit to view" title="Fit to view" icon={<Maximize size={14} aria-hidden />}
            onClick={() => { touched.current = false; fit() }} />
          <span className="grid size-7 place-items-center text-text-tertiary" tabIndex={0} role="img" aria-label="Click a step to edit. Ctrl or ⌘ + scroll to zoom. Drag to pan. Arrow keys move between steps."
            title="Click a step to edit · Ctrl/⌘ + scroll to zoom · drag to pan · arrow keys move between steps">
            <CircleHelp size={14} aria-hidden />
          </span>
        </div>
      </div>
      <div ref={box} className="relative min-w-0 flex-1 overflow-hidden">
        <div
          ref={viewport}
          role="group"
          aria-label="Pipeline graph. Use arrow keys to move between steps, Enter to edit one, Escape to close the editor."
          className="absolute inset-0 cursor-grab touch-none active:cursor-grabbing"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => { gesture.current = null }}
        >
          <div className="absolute left-0 top-0 origin-top-left" style={{ width, height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}>
            <svg width={width} height={height} className="pointer-events-none absolute inset-0" aria-hidden>
              <defs>
                <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M0,0 L8,4 L0,8 z" className="fill-text-tertiary" />
                </marker>
              </defs>
              {edges.map((e, i) => {
                const a = byId[e.from], b = byId[e.to]
                const muted = a.off || b.off
                const side = e.kind === 'branch' || e.kind === 'index'
                const d = toPath(routes[i], e.kind === 'index' ? 6 : e.kind === 'branch' ? 10 : 0)
                const flowing = e.kind !== 'index' && running.has(b.id)
                const hot = hoverEdge === i
                return (
                  <g key={i}>
                    {side && (
                      <path d={d} fill="none" stroke="transparent" strokeWidth={14} style={{ pointerEvents: 'stroke' }}
                        onPointerEnter={() => setHoverEdge(i)} onPointerLeave={() => setHoverEdge(null)} />
                    )}
                    <path d={d} fill="none" markerEnd={e.kind === 'index' ? undefined : 'url(#arrow)'} strokeWidth={flowing || hot ? 2.5 : 1.5}
                      style={{ pointerEvents: 'none', ...(flowing ? { stroke: 'var(--color-accent-default)' } : null) }}
                      strokeDasharray={flowing ? '8 6' : e.kind === 'index' ? '2 4' : e.kind === 'branch' ? '6 4' : undefined}
                      className={cn(flowing && 'edge-flow', 'stroke-text-tertiary', muted && !hot && 'opacity-35')} />
                  </g>
                )
              })}
            </svg>
            <span className="absolute text-caption font-medium uppercase tracking-wide text-text-tertiary" style={{ left: PAD, top: PAD - 2 }}>
              Indexing · offline, when documents change
            </span>
            {hotLabel?.label && hoverEdge !== null && (() => {
              // Label sits on the middle of the edge's longest run.
              const pts = routes[hoverEdge]
              let best: [Pt, Pt] = [pts[0], pts[1]]
              for (let i = 1; i < pts.length - 1; i++) {
                const len = (q: [Pt, Pt]) => Math.hypot(q[1][0] - q[0][0], q[1][1] - q[0][1])
                if (len([pts[i], pts[i + 1]]) > len(best)) best = [pts[i], pts[i + 1]]
              }
              const x = (best[0][0] + best[1][0]) / 2, y = (best[0][1] + best[1][1]) / 2
              return <span className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded border border-border-default bg-bg-surface px-1.5 py-0.5 text-caption text-text-secondary shadow-sm" style={{ left: x, top: y - 4 }}>{hotLabel.label}</span>
            })()}
            {nodes.map((n) => {
              const p = pos(n)
              const path = n.id.startsWith('path-') ? (n.id.slice(5) as Path) : null
              const stage = n.slot && TOGGLE_SLOTS.includes(n.slot) ? n.slot : null
              const changed = n.slot && changedBySlot.get(n.slot)?.length
              const hasErr = n.slot && errors?.some((e) => e.slot === n.slot)
              const curType = n.slot ? (value[n.slot] as { type?: string } | undefined)?.type : undefined
              const noProvider = !!n.slot && !n.off && slotCat(n.slot)?.types.find((t) => t.type === curType)?.available === false
              // Timings belong to steps that are on; a step the draft switched off but the active version ran stays blank.
              const ms = n.off ? undefined : n.id === 'answer' ? live?.totalMs : live?.ms[n.id]
              const isRunning = running.has(n.id) || (n.id === 'answer' && live?.phase === 'running' && live.answer !== '' && !live.generating && !live.verifying)
              const skipped = !!live && !n.io && !n.off && familyOf(n.id) !== 'index' && ms === undefined && !isRunning && (live.skip || (live.phase === 'done' && !drafted))
              const toggle = path ? () => togglePath(path) : stage ? () => toggleStage(stage, !!n.off) : null
              const unused = n.off && (n.id === 'embed' || n.id === 'vector_store')
              const label = `${n.title}: ${n.sub}${n.off ? ' (off)' : ''}${hasErr ? ', has errors' : ''}${noProvider ? ', provider not connected' : ''}`
              return (
                <div
                  key={n.id}
                  data-node={n.id}
                  id={n.slot && !path && n.id !== 'expand' && n.id !== 'fuse' ? `canvas-${n.slot}` : n.id === 'fuse' ? 'canvas-retrieve' : undefined}
                  role={n.slot ? 'button' : undefined}
                  tabIndex={n.id === tabStop ? 0 : -1}
                  aria-label={n.slot ? `${label}. Edit` : label}
                  aria-pressed={n.slot ? selectedId === n.id : undefined}
                  title={unused ? 'Not used by keyword retrieval — still built, in case you switch to dense, hybrid or fused search.' : undefined}
                  onFocus={() => setFocusId(n.id)}
                  onKeyDown={(e) => onNodeKey(e, n)}
                  className={cn(
                    'group focus-ring absolute flex cursor-pointer select-none flex-col justify-center overflow-hidden rounded-md border pl-4 pr-2.5 shadow-sm transition-[opacity,box-shadow,border-color]',
                    n.off ? 'border-dashed border-border-strong bg-transparent opacity-50 shadow-none hover:opacity-90' : 'border-border-strong bg-bg-surface',
                    ms !== undefined && !isRunning && 'border-success-fg',
                    skipped && 'opacity-35',
                    isRunning && 'z-10 border-accent-default motion-safe:animate-pulse',
                    selectedId === n.id && 'ring-2 ring-accent-default ring-offset-2 ring-offset-bg-subtle',
                    hasErr && 'border-danger-fg',
                  )}
                  style={{ left: p.x, top: p.y, width: W, height: H, ...(isRunning ? { boxShadow: '0 0 0 4px var(--color-accent-subtle)' } : null) }}
                >
                  <span aria-hidden className="absolute inset-y-0 left-0 w-[3px]" style={{ background: FAMILY[familyOf(n.id)] }} />
                  {ms !== undefined && (
                    <span className="absolute right-1.5 top-1.5 flex items-center gap-0.5 text-[11px] font-semibold tabular-nums text-success-fg">
                      <Check size={11} aria-hidden />{ms < 1 ? '<1' : Math.round(ms)} ms{n.id === 'cache' && live?.skip && live.ms.cache !== undefined ? ' · hit' : ''}
                    </span>
                  )}
                  {(hasErr || noProvider || changed) && (
                    <span aria-label={hasErr ? 'has errors' : noProvider ? 'provider not connected' : 'changed'}
                      title={hasErr ? 'Has errors' : noProvider ? 'Provider not connected' : 'Changed'}
                      className={cn('absolute right-1.5 bottom-1.5 size-2 rounded-full', hasErr ? 'bg-danger-fg' : noProvider ? 'bg-warning-fg' : 'bg-accent-default')} />
                  )}
                  <span className="flex items-center gap-1.5">
                    {isRunning && <Spinner size={12} label="Running" />}
                    <span className={cn('truncate text-[13px] font-semibold leading-tight', n.off ? 'text-text-secondary' : 'text-text-primary')}>{n.title}</span>
                    {toggle && (
                      <button type="button" data-no-drag tabIndex={-1} role="switch" aria-checked={!n.off}
                        aria-label={`${n.title}: ${n.off ? 'off' : 'on'}. Toggle`} onClick={toggle}
                        className="focus-ring ml-auto shrink-0 rounded px-1.5 text-[11px] font-medium text-accent-text opacity-0 hover:bg-accent-subtle focus:opacity-100 group-hover:opacity-100">
                        {n.off ? 'Turn on' : 'Turn off'}
                      </button>
                    )}
                  </span>
                  <span className="mt-0.5 line-clamp-2 text-[12px] leading-[15px] text-text-secondary">{n.sub}</span>
                </div>
              )
            })}
          </div>
        </div>

        {(live?.error || (live && (live.answer || live.phase === 'running'))) && (
          <p className="absolute right-3 top-3 z-20 line-clamp-4 max-w-[380px] rounded-md border border-border-default bg-bg-surface px-2.5 py-1.5 text-caption shadow-sm"
            aria-live="polite">
            {live?.error ? <span className="text-danger-fg">{live.error}</span> : (
              <span className="text-text-secondary">
                {live?.totalMs !== undefined && <>{live.totalMs < 1 ? '<1' : Math.round(live.totalMs)} ms · </>}
                {live?.answer || (live?.verifying ? 'Checking the answer…' : 'Working…')}
              </span>
            )}
          </p>
        )}
      </div>
    </div>

      {sel && selected && (
        <aside className="z-20 flex w-[min(380px,100%)] shrink-0 flex-col border-l border-border-default bg-bg-surface max-lg:absolute max-lg:inset-y-0 max-lg:right-0 max-lg:shadow-lg"
          style={{ maxWidth: PANEL }} aria-label={`${sel.title} settings`}>
          <div className="flex shrink-0 items-start justify-between gap-2 border-b border-border-default px-4 py-3">
            <div className="min-w-0">
              <h2 className="text-heading-lg text-text-primary">{sel.title}</h2>
              {sel.description && <p className="mt-0.5 line-clamp-2 text-body-sm text-text-tertiary">{sel.description}</p>}
            </div>
            <Button size="sm" variant="ghost" className="-mr-1 shrink-0" iconOnly aria-label="Close (Esc)" title="Close (Esc)" icon={<X size={14} aria-hidden />} onClick={closePanel} />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            <StageCard compact n={catalog.indexOf(sel) + 1} slot={selected} catalog={sel} value={value[selected]} baseline={baseline?.[selected]}
              changes={changedBySlot.get(selected)} errors={errors} projectId={projectId}
              onChange={(c) => onChange({ ...value, [selected]: c })} />
          </div>
        </aside>
      )}
    </div>
  )
}
