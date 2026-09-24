import { useState } from 'react'
import { CircleCheck, CircleX, Play, TriangleAlert } from 'lucide-react'
import { errorMessage, useEvalRun, useEvalRuns, useRunEval, useVersions } from '@/api/hooks'
import { formatMs } from '@/api/format'
import type { EvalDiagnosis, EvalItem, EvalItemResult, EvalMetrics, EvalRun } from '@/api/types'
import { Badge, Banner, Button, Card, CardHeader, Select, Spinner, cn, useToast } from '@/components/ui'
import { EvalJobProgress } from './EvalJobProgress'

const CELL = 'px-2 py-2 first:pl-4 last:pr-4 align-middle'
const pct = (x: number) => `${Math.round(x * 100)}%`

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
    <span className={cn('ml-1.5 text-caption', up ? 'text-success-fg' : 'text-danger-fg')}>
      {up ? '▲' : '▼'} {pctFmt ? `${Math.abs(Math.round(d * 100))} pts` : Math.abs(d).toFixed(2)}
    </span>
  )
}

function configLine(m: EvalMetrics) {
  const c = m.config
  return `${c.retrieve} · top-k ${c.top_k} · rerank ${c.rerank} · ${c.chunk} · ${c.store}`
}

function RunsTable({ runs, selected, onSelect }: { runs: EvalRun[]; selected: string | null; onSelect: (id: string) => void }) {
  let prev: EvalMetrics | undefined
  const rows = runs.map((r) => {
    const before = prev
    if (r.metrics) prev = r.metrics
    return { r, before }
  })
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-left">
        <caption className="sr-only">Evaluation runs, oldest first, with change from the previous run</caption>
        <thead>
          <tr className="h-9 border-b border-border-default bg-bg-subtle text-caption text-text-tertiary">
            <th scope="col" className={cn(CELL, 'py-0 font-medium')}>Version</th>
            <th scope="col" className={cn(CELL, 'py-0 font-medium')}>Configuration</th>
            <th scope="col" className={cn(CELL, 'py-0 text-right font-medium')}>Hit@1</th>
            <th scope="col" className={cn(CELL, 'py-0 text-right font-medium')}>Hit@k</th>
            <th scope="col" className={cn(CELL, 'py-0 text-right font-medium')}>MRR</th>
            <th scope="col" className={cn(CELL, 'py-0 text-right font-medium')}>p50</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ r, before }) => {
            const m = r.metrics
            const isSel = r.id === selected
            return (
              <tr
                key={r.id}
                onClick={() => onSelect(r.id)}
                className={cn('cursor-pointer border-b border-border-default last:border-b-0 hover:bg-bg-subtle', isSel && 'bg-accent-subtle')}
              >
                <td className={CELL}>
                  <button type="button" className="focus-ring rounded-sm text-label" onClick={() => onSelect(r.id)} aria-pressed={isSel}>
                    v{r.version ?? '?'}
                  </button>
                </td>
                <td className={cn(CELL, 'text-body-sm text-text-secondary')}>
                  {r.status === 'running' ? <span className="flex items-center gap-2"><Spinner size={12} label="" /> Running…</span>
                    : r.status === 'failed' ? <span className="text-danger-fg">Failed: {r.error}</span>
                    : m ? configLine(m) : '—'}
                </td>
                {m ? (
                  <>
                    <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}>{pct(m.hit_at_1)}<Delta now={m.hit_at_1} before={before?.hit_at_1} /></td>
                    <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}>{pct(m.hit_at_k)}<Delta now={m.hit_at_k} before={before?.hit_at_k} /></td>
                    <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums')}>{m.mrr.toFixed(2)}<Delta now={m.mrr} before={before?.mrr} pctFmt={false} /></td>
                    <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums text-text-secondary')}>{formatMs(m.p50_ms)}</td>
                  </>
                ) : (
                  <td colSpan={4} />
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border-default bg-bg-surface px-3 py-2">
      <dt className="text-caption text-text-tertiary">{label}</dt>
      <dd className="mt-0.5 font-mono text-title tabular-nums text-text-primary">{value}</dd>
      {hint && <dd className="text-caption text-text-tertiary">{hint}</dd>}
    </div>
  )
}

function ResultRow({ res, item }: { res: EvalItemResult; item?: EvalItem }) {
  const diag = res.diagnosis ? DIAGNOSIS[res.diagnosis] : null
  return (
    <tr className="border-b border-border-default last:border-b-0">
      <td className={cn(CELL, 'text-body')}>{item?.question ?? res.item_id}</td>
      <td className={cn(CELL, 'w-28')}>
        {res.hit ? (
          <Badge tone="success" icon={<CircleCheck aria-hidden />}>Rank #{res.rank}</Badge>
        ) : (
          <Badge tone="danger" icon={<CircleX aria-hidden />}>Miss</Badge>
        )}
      </td>
      <td className={cn(CELL, 'w-72 text-body-sm')}>
        {diag ? (
          <span title={diag.fix}>
            <span className="text-warning-fg">{diag.label}{res.deep_rank ? ` (#${res.deep_rank})` : ''}</span>
            <span className="block text-caption text-text-tertiary">{diag.fix}</span>
          </span>
        ) : (
          <span className="text-text-tertiary">{item?.document ?? ''}</span>
        )}
      </td>
    </tr>
  )
}

function RunDetail({ projectId, runId, items }: { projectId: string; runId: string; items: EvalItem[] }) {
  const q = useEvalRun(projectId, runId)
  const [onlyMisses, setOnlyMisses] = useState(false)
  if (q.isPending) return <div className="p-4"><Spinner label="Loading results" /></div>
  if (q.isError) return <p className="p-4 text-danger-fg">{errorMessage(q.error)}</p>
  const run = q.data
  const m = run.metrics
  if (!m) return null
  const byId = new Map(items.map((i) => [i.id, i]))
  const shown = onlyMisses ? run.results.filter((r) => !r.hit) : run.results
  const misses = run.results.filter((r) => !r.hit).length
  return (
    <div className="flex flex-col gap-4 border-t border-border-default p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-heading">v{run.version} · {m.n} questions</h3>
        <span className="text-body-sm text-text-tertiary">{configLine(m)}</span>
      </div>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat label="Hit@1" value={pct(m.hit_at_1)} hint="right chunk ranked first" />
        <Stat label="Hit@3" value={pct(m.hit_at_3)} />
        <Stat label={`Hit@${m.k}`} value={pct(m.hit_at_k)} hint="reaches the prompt" />
        <Stat label="MRR" value={m.mrr.toFixed(2)} hint="1.0 = always first" />
        <Stat label="Retrieval p50" value={formatMs(m.p50_ms)} />
      </dl>
      {misses > 0 && (
        <Banner tone="warning" icon={<TriangleAlert aria-hidden />} title={`${misses} miss${misses === 1 ? '' : 'es'}:`}>
          {(Object.keys(DIAGNOSIS) as EvalDiagnosis[])
            .filter((d) => m.diagnoses[d])
            .map((d) => `${m.diagnoses[d]} ${DIAGNOSIS[d].label.toLowerCase()}`)
            .join(' · ')}
        </Banner>
      )}
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-label text-text-secondary">Per question</h4>
        <label className="flex items-center gap-2 text-body-sm text-text-secondary">
          <input type="checkbox" checked={onlyMisses} onChange={(e) => setOnlyMisses(e.target.checked)} />
          Only misses
        </label>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border-default">
        <table className="w-full min-w-[720px] border-collapse text-left">
          <caption className="sr-only">Per-question retrieval results</caption>
          <thead>
            <tr className="h-9 border-b border-border-default bg-bg-subtle text-caption text-text-tertiary">
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
    </div>
  )
}

export function RunsPanel({ projectId, setId, items }: { projectId: string; setId: string; items: EvalItem[] }) {
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
  const active = versions.data?.find((v) => v.active)
  const options = (versions.data ?? []).map((v) => ({ value: v.id, label: `v${v.version}${v.active ? ' (active)' : ''}${v.note ? ` — ${v.note}` : ''}` }))

  const run = () => {
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
    <Card padding="none" className="overflow-hidden">
      <div className="p-4">
        <CardHeader
          className="mb-0"
          title="Retrieval quality"
          description="Each question is run through the version's retriever (and reranker). A hit means a chunk containing the evidence came back, in any chunking."
          actions={
            <>
              <Select
                size="md"
                aria-label="Version to evaluate"
                options={options}
                value={versionId || active?.id || ''}
                onChange={(e) => setVersionId(e.target.value)}
              />
              <Button variant="primary" icon={<Play size={14} aria-hidden />} onClick={run} loading={start.isPending} disabled={!!jobId}>
                Run evaluation
              </Button>
            </>
          }
        />
        {jobId && (
          <EvalJobProgress
            className="mt-3"
            jobId={jobId}
            projectId={projectId}
            onEnd={() => {
              setJobId(null)
              void runs.refetch()
            }}
          />
        )}
      </div>
      {list.length > 0 ? (
        <>
          <div className="border-t border-border-default">
            <RunsTable runs={list} selected={selected} onSelect={setPicked} />
          </div>
          {selected && list.find((r) => r.id === selected)?.status === 'ready' && (
            <RunDetail projectId={projectId} runId={selected} items={items} />
          )}
        </>
      ) : (
        <p className="border-t border-border-default px-4 py-6 text-body text-text-secondary">
          No runs yet. Run the active version, then change the configuration and run again to compare.
        </p>
      )}
    </Card>
  )
}
