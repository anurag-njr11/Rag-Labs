import { useState, type ReactNode } from 'react'
import { ArrowDown, ArrowUp, Pin, Table } from 'lucide-react'
import { formatPages } from '@/api/format'
import type { Citation, RetrievedChunk } from '@/api/types'
import { Badge, Card, ChunkStateBadge, FoundByBadge, ScoreChip, Tooltip, cn } from '@/components/ui'
import { ProseChunk, TableChunk, normalizeSpans, previewStart, type Span } from './chunkText'

/** "A > B > C" → "A › B › C" */
export const formatHeading = (h: string) => h.split(/\s+>\s+/).filter(Boolean).join(' › ')

export function spansFor(chunk: RetrievedChunk, citations: Citation[]): Span[] {
  const raw = citations.filter((c) => c.chunk_id === chunk.id).flatMap((c) => c.spans)
  return normalizeSpans(raw, chunk.text.length)
}

export function isCited(chunk: RetrievedChunk, citations: Citation[]): boolean {
  return chunk.cited ?? citations.some((c) => c.chunk_id === chunk.id)
}

const PATH_ORDER = ['dense', 'keyword', 'exact'] as const

export interface SourceItemProps {
  chunk: RetrievedChunk
  citations: Citation[]
  /** Answer finished — "cited" state is final. */
  final: boolean
  selected: boolean
  flashing: boolean
  domId: string
}

export function SourceItem({ chunk, citations, final, selected, flashing, domId }: SourceItemProps) {
  const [expanded, setExpanded] = useState(false)
  const spans = spansFor(chunk, citations)
  const cited = final && isCited(chunk, citations)
  const pages = formatPages(chunk.page_start, chunk.page_end)
  const heading = formatHeading(chunk.heading_path)
  const reranked = chunk.retrieval_rank !== chunk.rank
  const dropped = !chunk.in_context
  const long = chunk.text.length > 320 || chunk.text.split('\n').length > 4
  const from = expanded ? 0 : previewStart(chunk.text, spans)
  const paths = PATH_ORDER.filter((p) => chunk.found_by.includes(p))
  // `pinned` is newer than the shared RetrievedChunk type — read it defensively.
  const pinned = (chunk as RetrievedChunk & { pinned?: boolean }).pinned === true
  const defines = chunk.exact_keys.find((k) => k.startsWith('heading:'))?.slice('heading:'.length)
  const keys = [...new Set(chunk.exact_keys)].sort((a, b) => Number(b.startsWith('heading:')) - Number(a.startsWith('heading:')) || a.length - b.length)

  return (
    <Card
      id={domId}
      tabIndex={-1}
      padding="md"
      selected={selected}
      aria-label={`Source ${chunk.rank}: ${chunk.document}`}
      className={cn('scroll-mt-3 space-y-2 outline-none', flashing && 'animate-flash', dropped && !selected && 'opacity-60')}
    >
      {/* Row 1: rank, document, pages, state badges */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-bg-subtle font-mono text-mono-sm text-text-secondary">
          #{chunk.rank}
        </span>
        {reranked && (
          <Tooltip content={`Was #${chunk.retrieval_rank} before rerank`}>
            <span
              tabIndex={0}
              className={cn(
                'focus-ring inline-flex items-center gap-0.5 rounded-sm font-mono text-mono-sm',
                chunk.rank < chunk.retrieval_rank ? 'text-success-fg' : 'text-danger-fg',
              )}
              aria-label={`Was rank ${chunk.retrieval_rank} before rerank`}
            >
              {chunk.rank < chunk.retrieval_rank ? <ArrowUp size={11} aria-hidden /> : <ArrowDown size={11} aria-hidden />}
              {Math.abs(chunk.retrieval_rank - chunk.rank)}
            </span>
          </Tooltip>
        )}
        <span className="min-w-0 truncate text-heading text-text-primary" title={chunk.document}>{chunk.document}</span>
        {pages && <span className="shrink-0 font-mono text-mono-sm text-text-tertiary">{pages}</span>}
        {chunk.context_n != null && (
          <span className="shrink-0 font-mono text-mono-sm text-accent-text" title={`Numbered [${chunk.context_n}] in the prompt`}>
            [{chunk.context_n}]
          </span>
        )}
        <span className="ml-auto flex flex-wrap items-center gap-1">
          {pinned && (
            <Badge tone="exact" icon={<Pin aria-hidden />} title="Moved to the top: this section defines the matched error / symbol">
              Pinned{defines ? ` · defines ${defines}` : ''}
            </Badge>
          )}
          {chunk.is_table && <Badge tone="neutral" icon={<Table aria-hidden />}>Table</Badge>}
          {cited && <ChunkStateBadge state="cited" />}
          <ChunkStateBadge state={dropped ? 'dropped' : 'in_context'} />
        </span>
      </div>

      {/* Row 2: heading path */}
      {heading && <p className="truncate text-body text-text-tertiary" title={heading}>{heading}</p>}

      {/* Row 3: found-by + scores */}
      <div className="flex flex-wrap items-center gap-1">
        {paths.map((p) => (
          <FoundByBadge key={p} path={p} />
        ))}
        {paths.length > 0 && <span aria-hidden className="mx-0.5 h-3 w-px bg-border-default" />}
        {chunk.scores.dense != null && <ScoreTip label="dense" rank={chunk.ranks.dense}><ScoreChip kind="dense" value={chunk.scores.dense} /></ScoreTip>}
        {chunk.scores.keyword != null && <ScoreTip label="keyword" rank={chunk.ranks.keyword}><ScoreChip kind="keyword" value={chunk.scores.keyword} /></ScoreTip>}
        {chunk.scores.exact != null && <ScoreTip label="exact" rank={chunk.ranks.exact}><ScoreChip kind="exact" value={chunk.scores.exact} /></ScoreTip>}
        <ScoreChip kind="fused" value={chunk.score} className={cn(dropped && 'line-through')} />
        {chunk.scores.rerank != null && <ScoreChip kind="rerank" value={chunk.scores.rerank} />}
      </div>

      {/* Exact keys */}
      {keys.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-caption text-text-tertiary">Matched</span>
          {keys.map((k) => {
            const heading = k.startsWith('heading:')
            const label = heading ? k.slice('heading:'.length) : k
            return (
              <code
                key={k}
                title={heading ? `Section heading matched: ${label}` : k}
                className="inline-flex max-w-full items-center gap-1 rounded-sm bg-exact-bg px-1.5 py-px font-mono text-mono-sm text-exact-fg"
              >
                {heading && <span className="font-sans text-caption opacity-75">heading</span>}
                <span className="truncate">{label}</span>
              </code>
            )
          })}
        </div>
      )}

      {/* Row 4: chunk text */}
      <div>
        {chunk.is_table ? (
          <div className={cn(!expanded && long && 'max-h-40 overflow-hidden')}>
            <TableChunk text={chunk.text} spans={spans} />
          </div>
        ) : (
          <ProseChunk text={chunk.text} spans={spans} from={from} className={cn(!expanded && 'line-clamp-4')} />
        )}
        {long && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="focus-ring mt-1 rounded-sm text-body text-accent-text hover:text-accent-hover"
          >
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
      </div>
    </Card>
  )
}

function ScoreTip({ label, rank, children }: { label: string; rank?: number; children: ReactNode }) {
  if (rank == null) return <>{children}</>
  return (
    <Tooltip content={`Rank #${rank} on the ${label} path`}>
      <span className="inline-flex">
        {children}
        <span className="sr-only">, rank {rank}</span>
      </span>
    </Tooltip>
  )
}
