import { useState, type ReactNode } from 'react'
import { ChevronRight, CircleCheck, CircleX, PartyPopper, Play } from 'lucide-react'
import { errorMessage, useEvalRun, useEvalRuns, useRunEval, useVersions } from '@/api/hooks'
import { formatMs } from '@/api/format'
import type { EvalDiagnosis, EvalItem, EvalItemResult, EvalMetrics, EvalRun, EvalRunDetail } from '@/api/types'
import { Badge, Button, Card, ProgressBar, Select, Spinner, Tabs, cn, useToast, type ProgressTone } from '@/components/ui'
import { EvalJobProgress } from './EvalJobProgress'

const CELL = 'px-3 py-3 first:pl-5 last:pr-5 align-middle'
const pct = (x: number) => `${Math.round(x * 100)}%`
/** Meter colour for a 0–1 score. */
const toneFor = (x: number): ProgressTone => (x >= 0.8 ? 'success' : x >= 0.5 ? 'warning' : 'danger')
const TONE_TEXT: Record<ProgressTone, string> = {
  success: 'text-success-fg',
  warning: 'text-warning-fg',
  danger: 'text-danger-fg',
  accent: 'text-accent-text',
  neutral: 'text-text-tertiary',
}

const DIAGNOSIS: Record<EvalDiagnosis, { label: string; fix: string }> = {
  dropped_by_rerank: { label: 'Dropped by reranker', fix: 'Retrieved, but the reranker cut it — raise Keep top N.' },
  ranked_below_k: { label: 'Ranked below top-k', fix: 'Found deeper in the ranking — raise top-k or add a reranker.' },
  not_retrieved: { label: 'Not retrieved', fix: 'Not in the top 50 at all — try another retriever, embedder or chunking.' },
}

function Delta({ now, before, pctFmt = true }: { now: number; before?: number; pctFmt?: boolean }) {
  if (before === undefined) return null
  const d = now - before
  if (Math.abs(d) < 0.005) return <span className="ml-1.5 text-caption text-text-tertiary">=</span>
  const up = d > 0
  return (
    <span className={cn('ml-1.5 whitespace-nowrap text-caption', up ? 'text-success-fg' : 'text-danger-fg')}>
      {up ? '▲' : '▼'} {pctFmt ? `${Math.abs(Math.round(d * 100))} pts` : Math.abs(d).toFixed(2)}
    </span>
  )
}

function configLine(m: EvalMetrics) {
  const c = m.config
  return `${c.retrieve} · top-k ${c.top_k} · rerank ${c.rerank} · ${c.chunk} · ${c.store}`
}

function verdict(x: number) {
  if (x >= 0.9) return 'Excellent'
  if (x >= 0.8) return 'Strong'
  if (x >= 0.6) return 'Fair'
  return 'Needs work'
}

// ------------------------------------------------------------------------------------------------ scorecard

/** Donut gauge for a 0–1 score, value in the middle. */
function Gauge({ value, label }: { value: number; label: string }) {
  const r = 52
  const c = 2 * Math.PI * r
  const tone = toneFor(value)
  return (
    <div className="relative size-36 shrink-0">
      <svg viewBox="0 0 120 120" className="size-full -rotate-90" role="img" aria-label={`${label}: ${pct(value)}`}>
        <circle cx="60" cy="60" r={r} fill="none" strokeWidth="10" className="stroke-bg-muted" />
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.max(0, Math.min(1, value)))}
          className={cn('stroke-current transition-[stroke-dashoffset] duration-500', TONE_TEXT[tone])}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-[30px] font-semibold leading-none tabular-nums text-text-primary">{pct(value)}</span>
        <span className="mt-1 text-body-sm text-text-tertiary">{label}</span>
      </div>
    </div>
  )
}

function Tile({ label, value, hint, meter, delta }: { label: string; value: string; hint?: string; meter?: number; delta?: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border-default bg-bg-surface p-4">
      <dt className="text-label text-text-secondary">{label}</dt>
      <dd className="flex items-baseline font-mono text-display tabular-nums text-text-primary">
        {value}
        {delta}
      </dd>
      {meter != null && <dd><ProgressBar value={meter} tone={toneFor(meter)} aria-label={label} /></dd>}
      {hint && <dd className="text-body-sm text-text-tertiary">{hint}</dd>}
    </div>
  )
}

function Scorecard({ run, before }: { run: EvalRunDetail; before?: EvalMetrics }) {
  const m = run.metrics!
  const hits = run.results.filter((r) => r.hit).length
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(260px,320px)_minmax(0,1fr)]">
      <div className="flex items-center gap-5 rounded-xl bg-bg-subtle p-5">
        <Gauge value={m.hit_at_k} label={`Hit@${m.k}`} />
        <div className="min-w-0">
          <p className={cn('text-title-lg', TONE_TEXT[toneFor(m.hit_at_k)])}>{verdict(m.hit_at_k)}</p>
          <p className="mt-1 text-body-lg text-text-secondary">
            {hits} of {m.n} questions reach the prompt
            <Delta now={m.hit_at_k} before={before?.hit_at_k} />
          </p>
          <p className="mt-2 text-body-sm text-text-tertiary">v{run.version} · top-{m.k} passages sent to the model</p>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Tile label="Hit@1" value={pct(m.hit_at_1)} meter={m.hit_at_1} hint="right chunk ranked first" delta={<Delta now={m.hit_at_1} before={before?.hit_at_1} />} />
        <Tile label="Hit@3" value={pct(m.hit_at_3)} meter={m.hit_at_3} hint="in the top three" delta={<Delta now={m.hit_at_3} before={before?.hit_at_3} />} />
        <Tile label="MRR" value={m.mrr.toFixed(2)} meter={m.mrr} hint="1.0 = always first" delta={<Delta now={m.mrr} before={before?.mrr} pctFmt={false} />} />
        <Tile label="Retrieval p50" value={formatMs(m.p50_ms)} hint="median per question" />
      </dl>
    </div>
  )
}

// ------------------------------------------------------------------------------------------------ rail

/** Where the misses come from, with the fix for each cause. */
function MissBreakdown({ run }: { run: EvalRunDetail }) {
  const m = run.metrics!
  const misses = run.results.filter((r) => !r.hit).length
  if (misses === 0) {
    return (
      <Card padding="lg" className="flex items-start gap-3">
        <PartyPopper size={20} aria-hidden className="mt-0.5 shrink-0 text-success-fg" />
        <div>
          <h3 className="text-heading-lg text-text-primary">No misses</h3>
          <p className="mt-0.5 text-body text-text-secondary">Every question found its evidence in the top {m.k}.</p>
        </div>
      </Card>
    )
  }
  const causes = (Object.keys(DIAGNOSIS) as EvalDiagnosis[]).map((d) => ({ d, n: m.diagnoses[d] ?? 0 }))
  return (
    <Card padding="lg" className="flex flex-col gap-4">
      <div>
        <h3 className="text-heading-lg text-text-primary">Why questions missed</h3>
        <p className="mt-0.5 text-body text-text-secondary">
          {misses} of {m.n} missed. Fix the biggest cause first.
        </p>
      </div>
      <ul className="flex flex-col gap-4">
        {causes.map(({ d, n }) => (
          <li key={d} className={cn('flex flex-col gap-1.5', n === 0 && 'opacity-50')}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-heading text-text-primary">{DIAGNOSIS[d].label}</span>
              <span className="font-mono text-mono tabular-nums text-text-secondary">{n}</span>
            </div>
            <ProgressBar value={n / misses} tone={n ? 'warning' : 'neutral'} aria-label={`${DIAGNOSIS[d].label}: ${n}`} />
            {n > 0 && <p className="text-body-sm text-text-tertiary">{DIAGNOSIS[d].fix}</p>}
          </li>
        ))}
      </ul>
    </Card>
  )
}

function RunHistory({ runs, selected, onSelect }: { runs: EvalRun[]; selected: string | null; onSelect: (id: string) => void }) {
  let prev: EvalMetrics | undefined
  const rows = runs.map((r) => {
    const before = prev
    if (r.metrics) prev = r.metrics
    return { r, before }
  })
  return (
    <Card padding="none" className="overflow-hidden">
      <div className="p-5 pb-3">
        <h3 className="text-heading-lg text-text-primary">Run history</h3>
        <p className="mt-0.5 text-body text-text-secondary">Newest first. Pick a run to see its results.</p>
      </div>
      <ul className="flex flex-col gap-2 px-3 pb-3" aria-label="Evaluation runs">
        {rows.reverse().map(({ r, before }) => {
          const m = r.metrics
          const isSel = r.id === selected
          return (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => onSelect(r.id)}
                aria-pressed={isSel}
                disabled={r.status !== 'ready'}
                className={cn(
                  'focus-ring flex w-full flex-col gap-2 rounded-lg border px-3 py-2.5 text-left transition-colors',
                  isSel ? 'border-accent-default bg-accent-subtle' : 'border-transparent hover:bg-bg-subtle',
                )}
              >
                <span className="flex items-center gap-3">
                  <span className="text-heading text-text-primary">v{r.version ?? '?'}</span>
                  {m ? (
                    <>
                      <ProgressBar value={m.hit_at_k} tone={toneFor(m.hit_at_k)} className="flex-1" aria-label={`Hit@${m.k}`} />
                      <span className="whitespace-nowrap font-mono text-mono tabular-nums text-text-primary">
                        {pct(m.hit_at_k)}
                        <Delta now={m.hit_at_k} before={before?.hit_at_k} />
                      </span>
                    </>
                  ) : r.status === 'running' ? (
                    <span className="flex items-center gap-2 text-body-sm text-text-secondary"><Spinner size={12} label="" /> Running…</span>
                  ) : (
                    <span className="truncate text-body-sm text-danger-fg" title={r.error ?? ''}>Failed{r.error ? `: ${r.error}` : ''}</span>
                  )}
                </span>
                {m && (
                  <span className="flex items-center justify-between gap-2 text-body-sm text-text-tertiary">
                    <span className="truncate" title={configLine(m)}>{configLine(m)}</span>
                    <span className="shrink-0 font-mono text-mono-sm">MRR {m.mrr.toFixed(2)} · {formatMs(m.p50_ms)}</span>
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

// ------------------------------------------------------------------------------------------------ per question

function Outcome({ res }: { res: EvalItemResult }) {
  return res.hit ? (
    <Badge tone="success" icon={<CircleCheck aria-hidden />}>Rank #{res.rank}</Badge>
  ) : (
    <Badge tone="danger" icon={<CircleX aria-hidden />}>Miss</Badge>
  )
}

function Diagnosis({ res, item }: { res: EvalItemResult; item?: EvalItem }) {
  const diag = res.diagnosis ? DIAGNOSIS[res.diagnosis] : null
  if (!diag) return <span className="block truncate text-text-tertiary" title={item?.document ?? ''}>{item?.document ?? ''}</span>
  return (
    <span title={diag.fix}>
      <span className="text-warning-fg">{diag.label}{res.deep_rank ? ` (#${res.deep_rank})` : ''}</span>
      <span className="block text-body-sm text-text-tertiary">{diag.fix}</span>
    </span>
  )
}

/** Expanded detail: expected answer + what retrieval actually returned. */
function ResultDetail({ res, item }: { res: EvalItemResult; item?: EvalItem }) {
  return (
    <div className="grid gap-4 text-body-sm md:grid-cols-2">
      {item && (
        <dl className="grid content-start gap-2">
          <div>
            <dt className="text-text-tertiary">Expected answer</dt>
            <dd className="text-text-primary">{item.gold_answer}</dd>
          </div>
          <div>
            <dt className="text-text-tertiary">Evidence</dt>
            <dd className="mt-0.5 rounded-md border-l-2 border-accent-default bg-bg-subtle px-2 py-1 text-text-secondary">{item.evidence}</dd>
          </div>
        </dl>
      )}
      {res.top.length > 0 && (
        <div>
          <p className="text-text-tertiary">Retrieved</p>
          <ol className="mt-1 space-y-1">
            {res.top.slice(0, 5).map((t, i) => (
              <li key={t.id} className="flex items-start gap-2">
                <span className="w-5 shrink-0 text-right font-mono text-mono-sm text-text-tertiary">{i + 1}</span>
                <span className={cn('min-w-0 flex-1', t.hit ? 'text-success-fg' : 'text-text-secondary')}>
                  <span className="block truncate" title={t.document}>{t.document}</span>
                  {t.heading_path && <span className="block truncate text-text-tertiary" title={t.heading_path}>{t.heading_path.split(/\s+>\s+/).join(' › ')}</span>}
                </span>
                {t.hit && <CircleCheck size={14} aria-label="Contains the evidence" className="mt-0.5 shrink-0 text-success-fg" />}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

function ResultRow({ res, item }: { res: EvalItemResult; item?: EvalItem }) {
  const [open, setOpen] = useState(false)
  const question = item?.question ?? res.item_id
  return (
    <>
      <tr className={cn('border-b border-border-default last:border-b-0', open && 'border-b-0 bg-bg-subtle/50')}>
        <td className={CELL}>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="focus-ring flex items-start gap-2 rounded-sm text-left text-body-lg text-text-primary hover:text-accent-text"
          >
            <ChevronRight size={16} aria-hidden className={cn('mt-0.5 shrink-0 text-text-tertiary transition-transform', open && 'rotate-90')} />
            {question}
          </button>
        </td>
        <td className={cn(CELL, 'w-32')}><Outcome res={res} /></td>
        <td className={cn(CELL, 'w-72 max-w-72 text-body')}><Diagnosis res={res} item={item} /></td>
      </tr>
      {open && (
        <tr className="border-b border-border-default bg-bg-subtle/50">
          <td colSpan={3} className="px-5 pb-4 pl-11 pt-0">
            <ResultDetail res={res} item={item} />
          </td>
        </tr>
      )}
    </>
  )
}

function ResultCard({ res, item }: { res: EvalItemResult; item?: EvalItem }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="rounded-lg border border-border-default bg-bg-surface p-3">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="focus-ring flex w-full flex-col gap-2 rounded-sm text-left">
        <span className="text-body-lg text-text-primary">{item?.question ?? res.item_id}</span>
        <span className="flex flex-wrap items-center gap-2 text-body-sm">
          <Outcome res={res} />
          <span className="min-w-0 flex-1"><Diagnosis res={res} item={item} /></span>
        </span>
      </button>
      {open && <div className="mt-3 border-t border-border-default pt-3"><ResultDetail res={res} item={item} /></div>}
    </li>
  )
}

type Filter = 'all' | 'hits' | 'misses'

function PerQuestion({ run, items }: { run: EvalRunDetail; items: EvalItem[] }) {
  const [filter, setFilter] = useState<Filter>('all')
  const byId = new Map(items.map((i) => [i.id, i]))
  const hits = run.results.filter((r) => r.hit).length
  const misses = run.results.length - hits
  const shown = run.results.filter((r) => (filter === 'all' ? true : filter === 'hits' ? r.hit : !r.hit))
  return (
    <Card padding="none" className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 p-5">
        <div>
          <h3 className="text-heading-lg text-text-primary">Per question</h3>
          <p className="mt-0.5 text-body text-text-secondary">Click a question to see the expected answer and what came back.</p>
        </div>
        <Tabs<Filter>
          aria-label="Filter questions"
          value={filter}
          onChange={setFilter}
          items={[
            { value: 'all', label: 'All', count: run.results.length },
            { value: 'hits', label: 'Hits', count: hits },
            { value: 'misses', label: 'Misses', count: misses },
          ]}
        />
      </div>
      {shown.length === 0 ? (
        <p className="border-t border-border-default px-5 py-8 text-center text-body text-text-secondary">
          {filter === 'misses' ? 'No misses — every question found its evidence.' : 'Nothing to show.'}
        </p>
      ) : (
        <>
          <div className="hidden border-t border-border-default md:block">
            <table className="w-full border-collapse text-left">
              <caption className="sr-only">Per-question retrieval results</caption>
              <thead>
                <tr className="h-10 border-b border-border-default bg-bg-subtle text-label text-text-tertiary">
                  <th scope="col" className={cn(CELL, 'py-0 font-medium')}>Question</th>
                  <th scope="col" className={cn(CELL, 'py-0 font-medium')}>Gold chunk</th>
                  <th scope="col" className={cn(CELL, 'py-0 font-medium')}>Diagnosis / source</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => <ResultRow key={r.item_id} res={r} item={byId.get(r.item_id)} />)}
              </tbody>
            </table>
          </div>
          <ul className="flex flex-col gap-2 border-t border-border-default p-4 md:hidden" aria-label="Per-question retrieval results">
            {shown.map((r) => <ResultCard key={r.item_id} res={r} item={byId.get(r.item_id)} />)}
          </ul>
        </>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------------------------------------ panel

/**
 * Evaluate dashboard: a full-width scorecard (gauge + metric tiles) on top, then per-question results next to a
 * sticky rail (miss breakdown, run history, and `side` — the eval set card).
 */
export function RunsPanel({ projectId, setId, items, side }: { projectId: string; setId: string; items: EvalItem[]; side?: ReactNode }) {
  const versions = useVersions(projectId)
  const runs = useEvalRuns(projectId, setId)
  const start = useRunEval(projectId, setId)
  const { toast } = useToast()
  const [versionId, setVersionId] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)

  const list = runs.data ?? []
  const latestReady = [...list].reverse().find((r) => r.status === 'ready')
  const selected = picked && list.some((r) => r.id === picked) ? picked : latestReady?.id ?? null
  const selIdx = list.findIndex((r) => r.id === selected)
  const selReady = selIdx >= 0 && list[selIdx].status === 'ready'
  const before = selIdx > 0 ? list.slice(0, selIdx).reverse().find((r) => r.metrics)?.metrics ?? undefined : undefined
  const detail = useEvalRun(projectId, selReady ? selected : null)
  const run = detail.data?.metrics ? detail.data : undefined

  const active = versions.data?.find((v) => v.active)
  const options = (versions.data ?? []).map((v) => ({ value: v.id, label: `v${v.version}${v.active ? ' (active)' : ''}${v.note ? ` — ${v.note}` : ''}` }))

  const go = () => {
    start.mutate(
      { version_id: versionId || active?.id },
      {
        onSuccess: (r) => {
          setJobId(r.job_id)
          setPicked(r.run.id)
        },
        onError: (e) => toast({ tone: 'danger', title: 'Could not start the evaluation', description: errorMessage(e) }),
      },
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <Card padding="lg" className="flex flex-col gap-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 max-w-3xl">
            <h2 className="text-title-lg text-text-primary">Retrieval quality</h2>
            <p className="mt-1 text-body-lg text-text-secondary">
              Each question is run through the version's retriever (and reranker). A hit means a chunk containing the evidence came back, in any chunking.
            </p>
            {run && <p className="mt-2 text-body text-text-tertiary">{configLine(run.metrics!)}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              aria-label="Version to evaluate"
              options={options}
              value={versionId || active?.id || ''}
              onChange={(e) => setVersionId(e.target.value)}
              wrapperClassName="min-w-40"
            />
            <Button variant="primary" icon={<Play size={14} aria-hidden />} onClick={go} loading={start.isPending} disabled={!!jobId}>
              Run evaluation
            </Button>
          </div>
        </div>
        {jobId && (
          <EvalJobProgress
            jobId={jobId}
            projectId={projectId}
            onEnd={() => {
              setJobId(null)
              void runs.refetch()
            }}
          />
        )}
        {list.length === 0 ? (
          <p className="rounded-lg bg-bg-subtle px-4 py-6 text-center text-body-lg text-text-secondary">
            No runs yet. Run the active version, then change the configuration and run again to compare.
          </p>
        ) : detail.isPending && selReady ? (
          <Spinner label="Loading results" />
        ) : detail.isError ? (
          <p className="text-danger-fg">{errorMessage(detail.error)}</p>
        ) : run ? (
          <Scorecard run={run} before={before} />
        ) : null}
      </Card>

      {run ? (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
          <div className="order-2 min-w-0 xl:order-1">
            <PerQuestion run={run} items={items} />
          </div>
          <aside className="order-1 grid gap-6 md:grid-cols-2 xl:sticky xl:top-[calc(var(--topbar-h)+16px)] xl:order-2 xl:max-h-[calc(100dvh-var(--topbar-h)-32px)] xl:grid-cols-1 xl:overflow-y-auto xl:scrollbar-none" aria-label="Run insights">
            <MissBreakdown run={run} />
            <RunHistory runs={list} selected={selected} onSelect={setPicked} />
            <div className="md:col-span-2 xl:col-span-1">{side}</div>
          </aside>
        </div>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-2">
          {list.length > 0 && <RunHistory runs={list} selected={selected} onSelect={setPicked} />}
          {side}
        </div>
      )}
    </div>
  )
}
