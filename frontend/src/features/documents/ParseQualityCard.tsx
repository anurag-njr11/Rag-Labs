import { ArrowRight, TriangleAlert } from 'lucide-react'
import { formatNumber } from '@/api/format'
import type { Document } from '@/api/types'
import { HoverCard, QualityBadge, cn } from '@/components/ui'

const TITLE = { good: 'Good', fair: 'Fair', poor: 'Poor' } as const
const DOT = { good: 'bg-success-fg', fair: 'bg-warning-fg', poor: 'bg-danger-fg' } as const

function pagesList(pages: number[]): string {
  if (pages.length <= 6) return pages.join(', ')
  return `${pages.slice(0, 6).join(', ')}, …`
}

/** Parse-quality badge with a hover/focus card: warnings + stats + "View parsed text →". */
export function ParseQualityBadge({ doc, onViewChunks }: { doc: Document; onViewChunks?: () => void }) {
  const q = doc.parse_quality
  if (!q) return <span className="text-text-tertiary">—</span>
  const warnings = [...q.warnings]
  if (q.empty_page_count > 0 && !warnings.some((w) => /page/i.test(w))) {
    warnings.unshift(
      `${q.empty_page_count} page${q.empty_page_count === 1 ? ' has' : 's have'} little or no text (p. ${pagesList(q.empty_pages)})`,
    )
  }
  const stats: [string, string][] = [
    ['Pages', q.pages == null ? '—' : formatNumber(q.pages)],
    ['Tables found', formatNumber(q.tables)],
    ['Header lines removed', formatNumber(q.header_lines_removed)],
    ['Chunks', formatNumber(doc.chunks)],
    ['Characters', formatNumber(q.chars)],
    ['OCR', q.ocr_used ? 'Used' : 'Not used'],
  ]
  return (
    <HoverCard
      aria-label={`Parse quality ${TITLE[q.score]} — show details`}
      align="end"
      trigger={<QualityBadge score={q.score} />}
    >
      <div className="flex flex-col gap-3">
        <p className="flex items-center gap-2 text-heading">
          <span aria-hidden className={cn('size-1.5 rounded-full', DOT[q.score])} />
          Parse quality: {TITLE[q.score]}
        </p>
        {warnings.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {warnings.map((w, i) => (
              <li key={i} className="flex items-start gap-2 text-body-sm text-text-secondary">
                <TriangleAlert size={14} aria-hidden className="mt-px shrink-0 text-warning-fg" />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-body-sm text-text-secondary">No problems found while parsing.</p>
        )}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-border-default pt-3">
          {stats.map(([k, v]) => (
            <div key={k} className="flex flex-col gap-0.5">
              <dt className="text-caption text-text-tertiary">{k}</dt>
              <dd className="font-mono text-mono text-text-primary">{v}</dd>
            </div>
          ))}
        </dl>
        {onViewChunks && (
          <button
            type="button"
            onClick={onViewChunks}
            className="focus-ring inline-flex items-center gap-1 self-start rounded-sm text-label text-accent-text hover:underline"
          >
            View parsed text <ArrowRight size={12} aria-hidden />
          </button>
        )}
      </div>
    </HoverCard>
  )
}
