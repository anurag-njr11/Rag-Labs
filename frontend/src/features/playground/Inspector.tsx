import { useEffect, useRef, useState } from 'react'
import { PanelRightClose, Search } from 'lucide-react'
import { formatMs } from '@/api/format'
import { Banner, Button, EmptyState, FoundByBadge, Spinner, Tabs, cn, tabPanelProps } from '@/components/ui'
import { SourceItem, isCited } from './Sources'
import { TracePanel } from './Trace'
import { isActive, type Turn } from './session'

export type InspectorTab = 'sources' | 'trace'

export interface InspectorFocus {
  chunkId: string | null
  /** Bumped on each chip click so the same source can be flashed again. */
  tick: number
}

export const sourceDomId = (turnId: string, chunkId: string) => `src-${turnId}-${chunkId}`

export function inspectorSummary(turn: Turn | undefined): { retrieved: number; inContext: number; cited: number; latency?: number } {
  if (!turn) return { retrieved: 0, inContext: 0, cited: 0 }
  const final = turn.status === 'done'
  return {
    retrieved: turn.retrieved.length,
    inContext: turn.retrieved.filter((c) => c.in_context).length,
    cited: final ? turn.retrieved.filter((c) => isCited(c, turn.citations)).length : 0,
    latency: turn.totals?.latency_ms ?? turn.totals?.ms,
  }
}

export interface InspectorProps {
  turn: Turn | undefined
  tab: InspectorTab
  onTabChange: (t: InspectorTab) => void
  focus: InspectorFocus
  indexType?: string
  /** Hide the "Inspector" title row (mobile sheet has its own). */
  compact?: boolean
  /** Shows a "hide inspector" button in the header. */
  onCollapse?: () => void
  className?: string
}

export function Inspector({ turn, tab, onTabChange, focus, indexType, compact, onCollapse, className }: InspectorProps) {
  const scroller = useRef<HTMLDivElement>(null)
  const [flashId, setFlashId] = useState<string | null>(null)
  const s = inspectorSummary(turn)

  // Scroll to + flash the focused source when a citation chip is clicked.
  useEffect(() => {
    if (!turn || !focus.chunkId || tab !== 'sources') return
    const el = document.getElementById(sourceDomId(turn.id, focus.chunkId))
    if (!el) return
    el.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
    el.focus({ preventScroll: true })
    setFlashId(focus.chunkId)
    const t = setTimeout(() => setFlashId(null), 650)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus.tick, tab])

  // New turn → back to the top.
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 })
  }, [turn?.id])

  const summary = turn && turn.retrieved.length > 0 && (
    <p className="text-body text-text-tertiary">
      {s.retrieved} retrieved · {s.inContext} in context · {turn.status === 'done' ? `${s.cited} cited` : isActive(turn) ? 'citations pending' : '0 cited'}
    </p>
  )

  return (
    <section aria-label="Inspector" className={cn('flex min-h-0 flex-col', className)}>
      <div className={cn('shrink-0 space-y-2 border-b border-border-default px-5 pb-3', compact ? 'pt-1' : 'pt-4')}>
        <div className="flex flex-wrap items-center gap-3">
          {!compact && <h2 className="text-heading-lg text-text-primary">Inspector</h2>}
          <Tabs
            aria-label="Inspector view"
            idPrefix="inspector"
            value={tab}
            onChange={onTabChange}
            className={cn(!compact && 'ml-auto')}
            items={[
              { value: 'sources', label: 'Sources', count: turn?.retrieved.length || undefined },
              { value: 'trace', label: 'Trace' },
            ]}
          />
          {onCollapse && (
            <Button
              variant="ghost"
              size="sm"
              iconOnly
              aria-label="Hide inspector"
              title="Hide inspector"
              onClick={onCollapse}
              icon={<PanelRightClose size={16} aria-hidden />}
            />
          )}
        </div>
        {summary}
      </div>

      <div ref={scroller} {...tabPanelProps('inspector', tab)} className="relative min-h-0 flex-1 overflow-y-auto px-5 py-4 outline-none">
        {!turn ? (
          <EmptyState
            icon={<Search aria-hidden />}
            title="Nothing inspected yet"
            description="Ask a question — every retrieved passage appears here with how it was found, its scores, and whether the answer cited it."
            actions={
              <span className="flex flex-wrap justify-center gap-1">
                <FoundByBadge path="dense" /> <FoundByBadge path="keyword" /> <FoundByBadge path="exact" />
              </span>
            }
          />
        ) : tab === 'trace' ? (
          <TracePanel turn={turn} indexType={indexType} />
        ) : (
          <SourcesList turn={turn} focusId={focus.chunkId} flashId={flashId} />
        )}
      </div>
    </section>
  )
}

function SourcesList({ turn, focusId, flashId }: { turn: Turn; focusId: string | null; flashId: string | null }) {
  const active = isActive(turn)
  if (!turn.retrieved.length) {
    if (active) {
      return (
        <p className="flex items-center gap-2 py-8 text-body text-text-secondary" role="status">
          <Spinner size={14} /> {turn.indexMessage ? 'Updating the index first…' : 'Retrieving…'}
        </p>
      )
    }
    if (turn.status === 'error') {
      return (
        <Banner tone="info" title="No retrieval.">
          The request stopped before any passages were retrieved.
        </Banner>
      )
    }
    return <p className="py-8 text-body text-text-secondary">No passages were retrieved for this question.</p>
  }
  const final = turn.status === 'done'
  const noCitations = final && turn.citations.length === 0
  return (
    <div className="space-y-3">
      {noCitations && (
        <Banner tone="info" title="No sources cited.">
          {turn.truncated
            ? 'The answer was cut off before it cited any passage.'
            : "The model didn't use any of these passages — usually it couldn't find the answer in them."}
        </Banner>
      )}
      {turn.status === 'error' && (
        <p className="text-body-sm text-text-tertiary">Retrieval finished, but the answer failed — these are the passages that were sent to the model.</p>
      )}
      {[...turn.retrieved]
        .sort((a, b) => a.rank - b.rank)
        .map((c) => (
          <SourceItem
            key={c.id}
            domId={sourceDomId(turn.id, c.id)}
            chunk={c}
            citations={turn.citations}
            final={final}
            selected={focusId === c.id}
            flashing={flashId === c.id}
          />
        ))}
      {turn.totals && <p className="pt-1 text-center text-body-sm text-text-tertiary">Answered in {formatMs(turn.totals.latency_ms ?? turn.totals.ms)}</p>}
    </div>
  )
}
