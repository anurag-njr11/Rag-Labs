import { useJobEvents } from '@/api/hooks'
import { formatNumber } from '@/api/format'
import { ProgressBar, StatusBadge, cn } from '@/components/ui'
import { STAGE_LABELS } from '@/app/JobProgress'

/** One-line progress for eval generation / scoring jobs. */
export function EvalJobProgress({
  jobId, projectId, onEnd, className,
}: { jobId: string; projectId: string; onEnd?: () => void; className?: string }) {
  const s = useJobEvents(jobId, { projectId, onDone: onEnd, onFailed: onEnd })
  const cur = s.currentStage ? s.stages[s.currentStage] : undefined
  const value = s.status === 'done' ? 1 : cur && cur.total > 0 ? cur.done / cur.total : null
  const count = cur && cur.total > 0 ? `${formatNumber(cur.done)} / ${formatNumber(cur.total)}` : ''
  return (
    <div className={cn('flex min-w-0 flex-wrap items-center gap-3', className)} aria-live="polite">
      <StatusBadge
        withIcon
        status={s.status === 'failed' ? 'failed' : s.status === 'running' ? 'running' : 'done'}
        label={s.status === 'running' ? (cur ? STAGE_LABELS[cur.stage] : 'Starting…') : undefined}
      />
      <ProgressBar
        className="min-w-40 max-w-72 flex-1"
        value={value}
        tone={s.status === 'failed' ? 'danger' : s.status === 'done' ? 'success' : 'accent'}
        aria-label="Evaluation progress"
      />
      <span className="truncate text-body-sm text-text-tertiary">
        {s.status === 'failed' ? s.error : `${count} ${cur?.message ?? ''}`.trim()}
      </span>
    </div>
  )
}
