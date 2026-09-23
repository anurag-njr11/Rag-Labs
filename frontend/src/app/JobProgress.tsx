import { useState } from 'react'
import { ChevronRight, Circle, CircleCheck, CircleX, LoaderCircle, TriangleAlert } from 'lucide-react'
import { useJobEvents, type StageProgress } from '@/api/hooks'
import { formatNumber } from '@/api/format'
import type { JobDoneResult, JobStage } from '@/api/types'
import { Badge, ProgressBar, StatusBadge, cn } from '@/components/ui'

export const STAGE_LABELS: Record<JobStage, string> = {
  fetch: 'Fetch pages',
  parse: 'Parse documents',
  embed: 'Embed chunks',
  store: 'Write vector store',
  keywords: 'Build keyword index',
  ready: 'Ready',
}

export interface JobProgressProps {
  jobId: string | null | undefined
  /** Invalidated when the job ends (pass it whenever known). */
  projectId?: string
  /** Show the fetch stage even before it reports (URL imports). By default fetch shows only if it reports. */
  showFetch?: boolean
  /** 'full' = per-stage rows + logs + summary; 'compact' = single line (current stage + bar). */
  variant?: 'full' | 'compact'
  title?: string
  onDone?: (result: JobDoneResult) => void
  onFailed?: (error: string) => void
  className?: string
}

function StageIcon({ state }: { state: StageProgress['state'] }) {
  if (state === 'done') return <CircleCheck size={16} className="text-success-fg" aria-hidden />
  if (state === 'running') return <LoaderCircle size={16} className="animate-spin text-info-fg" aria-hidden />
  if (state === 'failed') return <CircleX size={16} className="text-danger-fg" aria-hidden />
  return <Circle size={16} className="text-text-disabled" aria-hidden />
}

function countLabel(p: StageProgress | undefined) {
  if (!p) return ''
  if (p.total > 0) return `${formatNumber(p.done)} / ${formatNumber(p.total)}`
  return p.done > 0 ? formatNumber(p.done) : ''
}

/** Live progress for an index build / URL fetch job (subscribes to /api/jobs/{id}/events). */
export function JobProgress({ jobId, projectId, showFetch, variant = 'full', title = 'Building index', onDone, onFailed, className }: JobProgressProps) {
  const s = useJobEvents(jobId, { projectId, onDone, onFailed })
  const [logsOpen, setLogsOpen] = useState(false)
  if (!jobId) return null

  const stages: JobStage[] = ['parse', 'embed', 'store', 'keywords', 'ready']
  if (showFetch || s.stages.fetch) stages.unshift('fetch')

  const rowState = (st: JobStage): StageProgress['state'] => {
    const p = s.stages[st]
    if (p) return p.state
    if (s.status === 'done') return 'done'
    return 'upcoming'
  }

  if (variant === 'compact') {
    const cur = s.currentStage ? s.stages[s.currentStage] : undefined
    const value = s.status === 'done' ? 1 : cur && cur.total > 0 ? cur.done / cur.total : null
    return (
      <div className={cn('flex min-w-0 items-center gap-3', className)} aria-live="polite">
        <StatusBadge
          withIcon
          status={s.status === 'done' ? 'done' : s.status === 'failed' ? 'failed' : s.status === 'lost' ? 'done' : 'running'}
          label={s.status === 'running' ? (cur ? STAGE_LABELS[cur.stage] : 'Starting…') : undefined}
        />
        <ProgressBar
          className="max-w-60 flex-1"
          value={value}
          tone={s.status === 'failed' ? 'danger' : s.status === 'done' ? 'success' : 'accent'}
          aria-label={title}
        />
        <span className="truncate text-body-sm text-text-tertiary">
          {s.status === 'failed' ? s.error : cur ? `${countLabel(cur)} ${cur.message}`.trim() : ''}
        </span>
      </div>
    )
  }

  const warnings = s.logs.filter((l) => l.level !== 'info')
  const stats = s.result?.build?.stats
  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-heading">{title}</h3>
        {s.status === 'done' && <StatusBadge status="done" />}
        {s.status === 'failed' && <StatusBadge status="failed" />}
        {s.status === 'running' && <StatusBadge status="running" withIcon />}
        {s.status === 'lost' && <Badge tone="neutral">Finished</Badge>}
      </div>

      <ol className="flex flex-col divide-y divide-border-default rounded-lg border border-border-default bg-bg-surface" aria-live="polite">
        {stages.map((st) => {
          const p = s.stages[st]
          const state = rowState(st)
          return (
            <li key={st} className="flex flex-col gap-1.5 px-3 py-2.5">
              <div className="flex items-center gap-2.5">
                <StageIcon state={state} />
                <span className={cn('text-label', state === 'upcoming' ? 'text-text-tertiary' : 'text-text-primary')}>{STAGE_LABELS[st]}</span>
                <span className="sr-only">{state}</span>
                <span className="ml-auto font-mono text-mono-sm text-text-tertiary">{countLabel(p)}</span>
              </div>
              {state === 'running' && st !== 'ready' && (
                <ProgressBar value={p && p.total > 0 ? p.done / p.total : null} aria-label={STAGE_LABELS[st]} />
              )}
              {p?.message && state !== 'upcoming' && <p className="pl-[26px] text-body-sm text-text-tertiary">{p.message}</p>}
            </li>
          )
        })}
      </ol>

      {s.status === 'failed' && s.error && (
        <p role="alert" className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-body text-danger-fg">{s.error}</p>
      )}

      {s.status === 'done' && s.result && (
        <p className="text-body-sm text-text-secondary">
          {s.result.fetch && `Fetched ${formatNumber(s.result.fetch.pages)} pages (${formatNumber(s.result.fetch.created)} new). `}
          {s.result.build ? `${formatNumber(s.result.build.chunk_count)} chunks indexed` : 'Not indexed yet'}
          {stats && ` in ${stats.seconds.toFixed(1)} s · ${formatNumber(stats.vectors_embedded)} embedded, ${formatNumber(stats.vectors_cached)} from cache`}
          {stats && stats.docs_failed > 0 && ` · ${stats.docs_failed} document(s) failed`}.
        </p>
      )}

      {s.logs.length > 0 && (
        <div>
          <button
            type="button"
            aria-expanded={logsOpen}
            onClick={() => setLogsOpen((o) => !o)}
            className="focus-ring flex items-center gap-1 rounded-sm text-label text-text-secondary hover:text-text-primary"
          >
            <ChevronRight size={14} aria-hidden className={cn('transition-transform', logsOpen && 'rotate-90')} />
            Log ({s.logs.length})
            {warnings.length > 0 && (
              <Badge tone="warning" icon={<TriangleAlert aria-hidden />} className="ml-1">
                {warnings.length}
              </Badge>
            )}
          </button>
          {logsOpen && (
            <pre className="mt-2 max-h-56 overflow-auto rounded-lg bg-bg-code p-3 font-mono text-mono text-text-code" tabIndex={0}>
              {s.logs.map((l, i) => (
                <div key={i} className={cn(l.level === 'error' && 'text-red-300', l.level === 'warning' && 'text-yellow-200')}>
                  {l.level !== 'info' && `[${l.level}] `}
                  {l.message}
                </div>
              ))}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
