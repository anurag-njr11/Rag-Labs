import { useState } from 'react'
import { Grid3x3, Rocket, Square, Star } from 'lucide-react'
import {
  errorMessage, useCancelSweep, useCreateVersion, useRuns, useStartSweep, useSweepAxes, useSweeps, useVersions,
} from '@/api/hooks'
import { formatMs, formatNumber } from '@/api/format'
import type { Judge, PipelineConfig, Sweep, SweepAxis, SweepCell } from '@/api/types'
import { Badge, Banner, Button, Card, EffectBadge, Field, Input, Select, Spinner, Switch, cn, useToast } from '@/components/ui'
import { EvalJobProgress } from './EvalJobProgress'

type Value = SweepAxis['values'][number]
type Scored = SweepCell & { metrics: NonNullable<SweepCell['metrics']> }

const CELL = 'px-3 py-2.5 first:pl-5 last:pr-5 align-middle'

/** System prompt + question, on top of the retrieved context (approx tokens). */
const PROMPT_OVERHEAD = 150

interface CostInputs {
  queries: number
  priceIn: number
  priceOut: number
  /** Answer tokens per query: the project's average from chat history, else 300. */
  outTokens: number
}

/** Projected monthly generation cost (PRD FR-2.33): context + overhead in, average answer out. */
function monthlyCost(ctxTokens: number, c: CostInputs): number {
  return (c.queries * ((ctxTokens + PROMPT_OVERHEAD) * c.priceIn + c.outTokens * c.priceOut)) / 1e6
}

const usd = (x: number) => (x >= 100 ? `$${Math.round(x).toLocaleString()}` : `$${x.toFixed(2)}`)

function CostControls({ value, onChange }: { value: CostInputs; onChange: (v: CostInputs) => void }) {
  const num = (k: keyof CostInputs) => (e: { target: { value: string } }) =>
    onChange({ ...value, [k]: Math.max(0, Number(e.target.value) || 0) })
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg bg-bg-subtle p-3">
      <Field label="Queries / month" className="w-36">{(f) => <Input id={f.id} type="number" min={0} value={value.queries} onChange={num('queries')} />}</Field>
      <Field label="$ / 1M input tokens" className="w-36">{(f) => <Input id={f.id} type="number" min={0} step="0.01" value={value.priceIn || ''} placeholder="0.00" onChange={num('priceIn')} />}</Field>
      <Field label="$ / 1M output tokens" className="w-36">{(f) => <Input id={f.id} type="number" min={0} step="0.01" value={value.priceOut || ''} placeholder="0.00" onChange={num('priceOut')} />}</Field>
      <p className="min-w-56 flex-1 pb-2 text-body-sm text-text-tertiary">
        Enter your model's prices to project monthly cost. Assumes ≈{value.outTokens} answer tokens per query
        (from your chat history) plus {PROMPT_OVERHEAD} tokens of prompt overhead. Free tiers cost $0.
      </p>
    </div>
  )
}

function getPath(cfg: PipelineConfig | undefined, path: string): unknown {
  const [slot, field] = path.split('.')
  return (cfg as Record<string, Record<string, unknown>> | undefined)?.[slot]?.[field]
}

function valueLabel(path: string, v: Value) {
  if (path === 'rerank.type') return v === 'none' ? 'off' : 'cross-encoder'
  if (path === 'embed.model') return String(v).split('/').pop()!
  return String(v).replace(/_/g, ' ')
}

const shortPath = (path: string) => path.replace('.type', '').replace('.', ' ').replace(/_/g, ' ')

/** "chunk size 512 · top k 5" — only the overrides that differ from the base config. */
function cellLabel(cell: SweepCell, base?: PipelineConfig) {
  const parts = Object.entries(cell.overrides)
    .filter(([p, v]) => !base || getPath(base, p) !== v)
    .map(([p, v]) => `${shortPath(p)} ${valueLabel(p, v)}`)
  return parts.length ? parts.join(' · ') : 'current settings'
}

const isBaseline = (cell: SweepCell, base?: PipelineConfig) =>
  !!base && Object.entries(cell.overrides).every(([p, v]) => getPath(base, p) === v)

/** Best first: MRR, then fewer context tokens. */
const rank = (a: Scored, b: Scored) => b.metrics.mrr - a.metrics.mrr || a.metrics.ctx_tokens - b.metrics.ctx_tokens

function insight(cells: Scored[], base?: PipelineConfig): string | null {
  if (cells.length < 2) return null
  const best = cells[0]
  const baseline = cells.find((c) => isBaseline(c, base))
  const parts: string[] = []
  if (baseline === best) parts.push(`Your current settings are already the best of the ${cells.length} tried.`)
  else if (baseline) {
    // from the rounded values shown, so 0.61 → 0.68 reads +0.07
    const d = Number(best.metrics.mrr.toFixed(2)) - Number(baseline.metrics.mrr.toFixed(2))
    parts.push(
      `${cellLabel(best, base)} lifts MRR from ${baseline.metrics.mrr.toFixed(2)} to ${best.metrics.mrr.toFixed(2)} (+${d.toFixed(2)}) ` +
        `at ${formatNumber(best.metrics.ctx_tokens)} context tokens per question (now ${formatNumber(baseline.metrics.ctx_tokens)}).`,
    )
  } else parts.push(`Best: ${cellLabel(best, base)}, MRR ${best.metrics.mrr.toFixed(2)}.`)
  const cheap = cells
    .filter((c) => c.pareto && c !== best && best.metrics.mrr - c.metrics.mrr <= 0.02 && c.metrics.ctx_tokens < best.metrics.ctx_tokens)
    .sort((a, b) => a.metrics.ctx_tokens - b.metrics.ctx_tokens)[0]
  if (cheap) {
    const saved = Math.round((1 - cheap.metrics.ctx_tokens / Math.max(1, best.metrics.ctx_tokens)) * 100)
    parts.push(`Within 0.02 MRR, ${cellLabel(cheap, base)} sends ${saved}% fewer tokens.`)
  }
  const graded = cells.filter((c) => c.metrics.answers?.n)
  if (graded.length > 1) {
    const top = [...graded].sort((a, b) => b.metrics.answers!.correct_rate - a.metrics.answers!.correct_rate)
    const [first, second] = top
    // overlapping 95% intervals = tied, not ranked (PRD FR-2.9)
    const tied = second.metrics.answers!.correct_ci[1] >= first.metrics.answers!.correct_ci[0]
    parts.push(tied
      ? `Answer quality of the ${graded.length} graded configurations is tied within noise (overlapping 95% intervals).`
      : `Best answers: ${cellLabel(first, base)}, ${Math.round(first.metrics.answers!.correct_rate * 100)}% correct.`)
  }
  return parts.join(' ')
}

// ------------------------------------------------------------------------------------------------ builder

function AxisPicker({
  axes, base, picked, onToggle, onSeed,
}: {
  axes: SweepAxis[]; base?: PipelineConfig; picked: Record<string, Value[]>
  onToggle: (path: string, v: Value) => void; onSeed: (path: string, values: Value[]) => void
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {axes.map((a) => {
        const current = getPath(base, a.path)
        return (
          <fieldset key={a.path} className="flex flex-col gap-2 rounded-lg border border-border-default p-3">
            <legend className="flex items-center gap-2 px-1 text-label text-text-secondary">
              {a.label} <EffectBadge effect={a.effect} />
              {a.seed && (
                <button type="button" className="focus-ring rounded-sm text-body-sm text-accent-text hover:underline"
                  title="Pick the 3 best models by self-reported MTEB retrieval score, plus your current one"
                  onClick={() => onSeed(a.path, [...new Set([...a.seed!, ...(current !== undefined ? [current as Value] : [])])])}>
                  MTEB top 3
                </button>
              )}
            </legend>
            <div className="flex flex-wrap gap-1.5">
              {a.values.map((v) => {
                const on = picked[a.path]?.includes(v) ?? false
                return (
                  <button
                    key={String(v)}
                    type="button"
                    aria-pressed={on}
                    onClick={() => onToggle(a.path, v)}
                    title={a.notes?.[String(v)] ?? String(v)}
                    className={cn(
                      'focus-ring h-7 rounded-full border px-3 text-body-sm transition-colors',
                      on ? 'border-accent-default bg-accent-subtle text-accent-text' : 'border-border-default text-text-secondary hover:bg-bg-subtle',
                    )}
                  >
                    {valueLabel(a.path, v)}
                    {a.scores && <span className="ml-1 font-mono text-mono-sm text-text-tertiary">{a.scores[String(v)]?.toFixed(1) ?? '—'}</span>}
                    {current === v && <span className="ml-1 text-text-tertiary">(current)</span>}
                  </button>
                )
              })}
            </div>
          </fieldset>
        )
      })}
    </div>
  )
}

// ------------------------------------------------------------------------------------------------ chart

/** Quality (MRR) vs. cost (context tokens per question), Pareto frontier drawn as a step line. */
function ParetoChart({ cells, base }: { cells: Scored[]; base?: PipelineConfig }) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 720, H = 280, L = 48, R = 16, T = 16, B = 40
  const xs = cells.map((c) => c.metrics.ctx_tokens)
  const xMin = Math.min(...xs), xMax = Math.max(...xs)
  const xPad = (xMax - xMin) * 0.08 || Math.max(1, xMax * 0.1)
  const x0 = Math.max(0, xMin - xPad), x1 = xMax + xPad
  const y0 = Math.max(0, Math.floor((Math.min(...cells.map((c) => c.metrics.mrr)) - 0.05) * 10) / 10)
  const y1 = 1
  const sx = (v: number) => L + ((v - x0) / (x1 - x0 || 1)) * (W - L - R)
  const sy = (v: number) => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B)
  const frontier = cells.filter((c) => c.pareto).sort((a, b) => a.metrics.ctx_tokens - b.metrics.ctx_tokens)
  const step = frontier
    .map((c, i) => {
      const x = sx(c.metrics.ctx_tokens), y = sy(c.metrics.mrr)
      return i === 0 ? `M${x},${y}` : `H${x}V${y}`
    })
    .join('')
  const yTicks = Array.from({ length: 5 }, (_, i) => y0 + ((y1 - y0) * i) / 4)
  const xTicks = Array.from({ length: 4 }, (_, i) => x0 + ((x1 - x0) * i) / 3)
  const h = hover != null ? cells[hover] : null
  return (
    // Capped width so the viewBox-scaled 11px labels stay ~11–13px on screen.
    <figure className="flex max-w-3xl flex-col gap-2">
      <div className="flex flex-wrap items-center gap-4 text-body-sm text-text-secondary">
        <span className="flex items-center gap-1.5"><span aria-hidden className="size-2.5 rounded-full bg-accent-default" /> Pareto frontier</span>
        <span className="flex items-center gap-1.5"><span aria-hidden className="size-2.5 rounded-full border-2 border-text-tertiary" /> Dominated</span>
        <span className="text-text-tertiary">Up and left is better.</span>
      </div>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Retrieval quality versus context tokens per question for each configuration">
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={L} x2={W - R} y1={sy(t)} y2={sy(t)} className="stroke-border-default" strokeDasharray="2 4" />
              <text x={L - 8} y={sy(t)} dy="0.32em" textAnchor="end" className="fill-text-tertiary text-[11px]">{t.toFixed(2)}</text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={t} x={sx(t)} y={H - B + 18} textAnchor="middle" className="fill-text-tertiary text-[11px]">{formatNumber(Math.round(t))}</text>
          ))}
          <text x={L} y={H - 4} className="fill-text-tertiary text-[11px]">Context tokens per question →</text>
          <text x={12} y={T} transform={`rotate(-90 12 ${T})`} textAnchor="end" className="fill-text-tertiary text-[11px]">MRR</text>
          {step && <path d={step} fill="none" strokeWidth={2} className="stroke-accent-default" opacity={0.5} />}
          {cells.map((c, i) => {
            const cx = sx(c.metrics.ctx_tokens), cy = sy(c.metrics.mrr)
            return (
              <g key={i}>
                {/* larger invisible hit target */}
                <circle
                  cx={cx} cy={cy} r={12} fill="transparent" tabIndex={0}
                  aria-label={`${cellLabel(c, base)}: MRR ${c.metrics.mrr.toFixed(2)}, ${c.metrics.ctx_tokens} tokens`}
                  onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(i)} onBlur={() => setHover(null)}
                  className="cursor-pointer outline-none"
                />
                <circle
                  cx={cx} cy={cy} r={hover === i ? 7 : 5} pointerEvents="none" strokeWidth={2}
                  className={c.pareto ? 'fill-accent-default stroke-bg-surface' : 'fill-bg-surface stroke-text-tertiary'}
                />
              </g>
            )
          })}
          {cells[0] && (
            <text x={sx(cells[0].metrics.ctx_tokens)} y={sy(cells[0].metrics.mrr) - 12} textAnchor="middle" className="fill-text-secondary text-[11px]">best</text>
          )}
        </svg>
        {h && (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 w-max max-w-64 rounded-md border border-border-default bg-bg-surface px-3 py-2 text-body-sm shadow-lg"
            style={{
              left: `${(sx(h.metrics.ctx_tokens) / W) * 100}%`,
              top: `calc(${(sy(h.metrics.mrr) / H) * 100}% - 10px)`,
              // keep the tooltip inside the chart near either edge
              translate: `${sx(h.metrics.ctx_tokens) / W < 0.25 ? '-10%' : sx(h.metrics.ctx_tokens) / W > 0.75 ? '-90%' : '-50%'} -100%`,
            }}
          >
            <p className="font-medium text-text-primary">{cellLabel(h, base)}</p>
            <p className="font-mono text-mono-sm text-text-secondary">
              MRR {h.metrics.mrr.toFixed(2)} · Hit@{h.metrics.k} {Math.round(h.metrics.hit_at_k * 100)}% · {formatNumber(h.metrics.ctx_tokens)} tok
            </p>
          </div>
        )}
      </div>
    </figure>
  )
}

// ------------------------------------------------------------------------------------------------ leaderboard

function Leaderboard({ sweep, base, onPromote, promoting, cost }: {
  sweep: Sweep; base?: PipelineConfig; onPromote: (c: SweepCell) => void; promoting: boolean; cost: CostInputs
}) {
  const priced = cost.priceIn > 0 || cost.priceOut > 0
  const scored = sweep.cells.filter((c): c is Scored => c.status === 'ready' && !!c.metrics).sort(rank)
  const broken = sweep.cells.filter((c) => c.status === 'failed' || c.status === 'invalid')
  const pending = sweep.cells.filter((c) => c.status === 'pending' || c.status === 'running').length
  const line = insight(scored, base)
  const graded = scored.some((c) => c.metrics.answers)
  return (
    <div className="flex flex-col gap-4">
      {line && <Banner tone="info">{line}</Banner>}
      {scored.length >= 2 && <ParetoChart cells={scored} base={base} />}
      <div className="overflow-x-auto rounded-lg border border-border-default">
        <table className="w-full min-w-[860px] border-collapse text-left">
          <caption className="sr-only">Sweep leaderboard, best first</caption>
          <thead>
            <tr className="h-10 border-b border-border-default bg-bg-subtle text-label text-text-tertiary">
              <th scope="col" className={cn(CELL, 'font-medium')}>Configuration</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')}>MRR</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')} title="Normalised discounted cumulative gain at k">nDCG@k</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')}>Hit@1</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')}>Hit@k</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')} title="Evidence survives the prompt's context budget">In context</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')}>Tokens / q</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')}>p50</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')}>p95</th>
              {graded && <th scope="col" className={cn(CELL, 'text-right font-medium')} title="LLM-graded, with 95% interval">Answers ✓</th>}
              {priced && <th scope="col" className={cn(CELL, 'text-right font-medium')}>$ / month</th>}
              <th scope="col" className={cn(CELL, 'font-medium')}><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {scored.map((c, i) => {
              const m = c.metrics
              const baseline = isBaseline(c, base)
              return (
                <tr key={i} className="border-b border-border-default last:border-b-0">
                  <td className={CELL}>
                    <span className="flex flex-wrap items-center gap-1.5 text-body text-text-primary">
                      {c.pareto && <Star size={14} aria-label="On the Pareto frontier" className="shrink-0 fill-accent-default text-accent-default" />}
                      {cellLabel(c, base)}
                      {baseline && <Badge tone="neutral">current</Badge>}
                    </span>
                  </td>
                  <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums text-text-primary')}>{m.mrr.toFixed(2)}</td>
                  <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}>{m.ndcg_at_k != null ? m.ndcg_at_k.toFixed(2) : '—'}</td>
                  <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}>{Math.round(m.hit_at_1 * 100)}%</td>
                  <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}>{Math.round(m.hit_at_k * 100)}% <span className="text-text-tertiary">@{m.k}</span></td>
                  <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}>{Math.round(m.context_hit * 100)}%</td>
                  <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}>{formatNumber(m.ctx_tokens)}</td>
                  <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums text-text-secondary')}>{formatMs(m.p50_ms)}</td>
                  <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums text-text-secondary')}>{m.p95_ms != null ? formatMs(m.p95_ms) : '—'}</td>
                  {graded && (
                    <td
                      className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}
                      title={c.grade_error ?? (m.answers ? `95% CI ${Math.round(m.answers.correct_ci[0] * 100)}–${Math.round(m.answers.correct_ci[1] * 100)}%${m.answers.rejudged ? ' · median of 3 judgings (close to the leader)' : ''}${m.answers.judge ? ` · judge ${m.answers.judge}` : ''}` : 'not graded')}
                    >
                      {m.answers ? `${Math.round(m.answers.correct_rate * 100)}%${m.answers.rejudged ? ' ×3' : ''}` : <span className="text-text-tertiary">—</span>}
                    </td>
                  )}
                  {priced && (
                    <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}>{usd(monthlyCost(m.ctx_tokens, cost))}</td>
                  )}
                  <td className={cn(CELL, 'text-right')}>
                    {!baseline && (
                      <Button size="sm" variant={i === 0 ? 'primary' : 'secondary'} icon={<Rocket size={14} aria-hidden />} onClick={() => onPromote(c)} disabled={promoting}>
                        Promote
                      </Button>
                    )}
                  </td>
                </tr>
              )
            })}
            {pending > 0 && (
              <tr><td colSpan={10 + Number(graded) + Number(priced)} className={cn(CELL, 'text-body-sm text-text-tertiary')}>{pending} configuration{pending === 1 ? '' : 's'} still to score…</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {broken.length > 0 && (
        <details className="text-body-sm text-text-secondary">
          <summary className="cursor-pointer">{broken.length} configuration{broken.length === 1 ? '' : 's'} couldn't run</summary>
          <ul className="mt-2 flex flex-col gap-1">
            {broken.map((c, i) => <li key={i}><span className="text-text-primary">{cellLabel(c)}</span> — {c.error}</li>)}
          </ul>
        </details>
      )}
    </div>
  )
}

// ------------------------------------------------------------------------------------------------ panel

/**
 * Sweeps: pick a base version and a few axes, score every combination on the eval set (no LLM calls),
 * then read the leaderboard + Pareto chart and promote a winner into a new active version.
 */
export function SweepsPanel({ projectId, setId, judge }: { projectId: string; setId: string; judge?: Judge | null }) {
  const axesQ = useSweepAxes(projectId)
  const versions = useVersions(projectId)
  const sweeps = useSweeps(projectId)
  const start = useStartSweep(projectId)
  const cancel = useCancelSweep(projectId)
  const promote = useCreateVersion(projectId)
  const { toast } = useToast()
  const [versionId, setVersionId] = useState('')
  const [picked, setPicked] = useState<Record<string, Value[]>>({})
  const [jobId, setJobId] = useState<string | null>(null)
  const [shownId, setShownId] = useState<string | null>(null)
  const [autoOpt, setAutoOpt] = useState(false)
  const runs = useRuns(projectId, 50)
  const outs = (runs.data ?? []).map((r) => r.tokens_out ?? 0).filter((t) => t > 0)
  const [prices, setPrices] = useState({ queries: 10000, priceIn: 0, priceOut: 0 })
  const cost: CostInputs = { ...prices, outTokens: outs.length ? Math.round(outs.reduce((a, b) => a + b, 0) / outs.length) : 300 }

  const active = versions.data?.find((v) => v.active)
  const baseVersion = versions.data?.find((v) => v.id === (versionId || active?.id))
  const base = baseVersion?.config
  const axes = (axesQ.data?.axes ?? []).filter((a) => Object.entries(a.requires ?? {}).every(([p, v]) => getPath(base, p) === v))
  const max = axesQ.data?.max_cells ?? 48
  const chosen = Object.entries(picked).filter(([, v]) => v.length)
  const count = chosen.length ? chosen.reduce((n, [, v]) => n * v.length, 1) : 0

  const list = (sweeps.data ?? []).filter((s) => s.eval_set_id === setId)
  const shown = list.find((s) => s.id === shownId) ?? list[0]
  const shownBase = versions.data?.find((v) => v.id === shown?.base_version_id)?.config

  const toggle = (path: string, v: Value) =>
    setPicked((p) => {
      const cur = p[path] ?? []
      return { ...p, [path]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] }
    })

  const go = () =>
    start.mutate(
      { set_id: setId, version_id: baseVersion?.id, axes: chosen.map(([path, values]) => ({ path, values })), auto_optimize: autoOpt, judge: judge ?? undefined },
      {
        onSuccess: (r) => {
          setJobId(r.job_id)
          setShownId(r.sweep.id)
        },
        onError: (e) => toast({ tone: 'danger', title: 'Could not start the sweep', description: errorMessage(e) }),
      },
    )

  const doPromote = (c: SweepCell) =>
    c.config &&
    promote.mutate(
      { config: c.config, note: `Sweep: ${cellLabel(c, shownBase)}`.slice(0, 300), activate: true, build: true },
      {
        onSuccess: (r) =>
          toast({
            tone: 'success',
            title: r.unchanged ? `Already active as v${r.version.version}` : `Promoted to v${r.version.version}`,
            description: r.unchanged ? undefined : 'Now active and serving the Playground and API.',
          }),
        onError: (e) => toast({ tone: 'danger', title: 'Could not promote', description: errorMessage(e) }),
      },
    )

  const running = shown?.status === 'running'
  const options = (versions.data ?? []).map((v) => ({ value: v.id, label: `v${v.version}${v.active ? ' (active)' : ''}` }))

  return (
    <Card padding="lg" className="flex flex-col gap-5 sm:p-6">
      <div className="max-w-3xl">
        <h2 className="flex items-center gap-2 text-title-lg text-text-primary"><Grid3x3 size={20} aria-hidden /> Sweep configurations</h2>
        <p className="mt-1 text-body-lg text-text-secondary">
          Score every combination of the values you pick on this eval set — retrieval only, so no LLM calls, except query expansion
          (multi-query / HyDE), which makes one call per question. Rebuild axes build one index per value (parsing and embeddings
          are cached); instant axes reuse it.
        </p>
      </div>

      {axesQ.isPending || versions.isPending ? (
        <Spinner label="Loading sweep options" />
      ) : (
        <>
          <AxisPicker axes={axes} base={base} picked={picked} onToggle={toggle} onSeed={(path, values) => setPicked((p) => ({ ...p, [path]: values }))} />
          <div className="flex flex-wrap items-center gap-3">
            <Select aria-label="Base version" options={options} value={baseVersion?.id ?? ''} onChange={(e) => setVersionId(e.target.value)} wrapperClassName="min-w-36" />
            <span className={cn('text-body', count > max ? 'text-danger-fg' : 'text-text-secondary')}>
              {count === 0 ? 'Pick values on at least one axis.' : `${count} configuration${count === 1 ? '' : 's'}${count > max ? ` — the limit is ${max}` : ''}`}
            </span>
            <label className="ml-auto flex items-center gap-2 text-body-sm text-text-secondary" title="After scoring retrieval for every configuration, write and grade answers for the best 25% (at most 5); configurations within noise of the leader are graded 3 times and take the median. Uses LLM calls.">
              <Switch checked={autoOpt} onChange={setAutoOpt} aria-label="Auto-Optimize" />
              Auto-Optimize: grade answers of the best
            </label>
            <Button variant="primary" onClick={go} loading={start.isPending} disabled={count === 0 || count > max || running || !!jobId}>
              Run sweep
            </Button>
          </div>
        </>
      )}

      {jobId && (
        <EvalJobProgress jobId={jobId} projectId={projectId} onEnd={() => { setJobId(null); void sweeps.refetch() }} />
      )}

      {shown && (
        <div className="flex flex-col gap-4 border-t border-border-default pt-5">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-heading-lg text-text-primary">Leaderboard</h3>
            <span className="text-body-sm text-text-tertiary">
              base v{shown.base_version ?? '?'} · {shown.axes.map((a) => shortPath(a.path)).join(' × ')}
            </span>
            {shown.status === 'cancelled' && <Badge tone="warning">cancelled</Badge>}
            {shown.status === 'failed' && <Badge tone="danger">failed</Badge>}
            <div className="ml-auto flex items-center gap-2">
              {list.length > 1 && (
                <Select
                  aria-label="Show sweep"
                  options={list.map((s, i) => ({ value: s.id, label: `${i === 0 ? 'Latest' : new Date(s.created_at).toLocaleString()} · ${s.cells.length} configs` }))}
                  value={shown.id}
                  onChange={(e) => setShownId(e.target.value)}
                />
              )}
              {running && (
                <Button variant="secondary" icon={<Square size={14} aria-hidden />} onClick={() => cancel.mutate(shown.id)} loading={cancel.isPending}>
                  Stop
                </Button>
              )}
            </div>
          </div>
          {shown.error && <p role="alert" className="text-body-sm text-danger-fg">{shown.error}</p>}
          <CostControls value={cost} onChange={({ queries, priceIn, priceOut }) => setPrices({ queries, priceIn, priceOut })} />
          <LeaderboardOrEmpty sweep={shown} base={shownBase} onPromote={doPromote} promoting={promote.isPending} cost={cost} />
        </div>
      )}
    </Card>
  )
}

function LeaderboardOrEmpty(props: { sweep: Sweep; base?: PipelineConfig; onPromote: (c: SweepCell) => void; promoting: boolean; cost: CostInputs }) {
  const ready = props.sweep.cells.some((c) => c.status === 'ready')
  if (!ready && props.sweep.status === 'running') return <Spinner label="Scoring the first configuration" />
  return <Leaderboard {...props} />
}
