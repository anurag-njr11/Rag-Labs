import { useState } from 'react'
import { Search, Table } from 'lucide-react'
import { errorMessage, useDocumentChunks } from '@/api/hooks'
import { formatNumber, formatPages } from '@/api/format'
import type { Document } from '@/api/types'
import { Badge, Button, Dialog, EmptyState, Input, Spinner } from '@/components/ui'

/** Dialog listing a document's chunks in the active index (GET …/documents/{doc}/chunks). */
export function ChunkViewer({ projectId, doc, onClose }: { projectId: string; doc: Document | null; onClose: () => void }) {
  const [limit, setLimit] = useState(200)
  const [filter, setFilter] = useState('')
  const q = useDocumentChunks(projectId, doc?.id, limit)
  const chunks = (q.data?.chunks ?? []).filter(
    (c) => !filter || c.text.toLowerCase().includes(filter.toLowerCase()) || c.heading_path.toLowerCase().includes(filter.toLowerCase()),
  )

  return (
    <Dialog
      open={!!doc}
      onClose={onClose}
      size="xl"
      title={<span className="font-mono text-heading">{doc?.filename}</span>}
      description={
        q.data ? `${formatNumber(q.data.total)} chunks in the active index` : 'Chunks in the active index'
      }
    >
      <div className="flex flex-col gap-3">
        <Input
          icon={<Search />}
          placeholder="Filter chunks"
          aria-label="Filter chunks"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          wrapperClassName="sm:max-w-xs"
        />
        {q.isPending ? (
          <div className="flex justify-center py-12 text-text-tertiary"><Spinner size={20} /></div>
        ) : q.isError ? (
          <p role="alert" className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger-fg">{errorMessage(q.error)}</p>
        ) : q.data.total === 0 ? (
          <EmptyState title="No chunks yet" description="This document isn't in the active index. Build the index to chunk it." />
        ) : (
          <ol className="flex flex-col gap-2">
            {chunks.map((c) => (
              <li key={c.id} className="rounded-lg border border-border-default bg-bg-surface p-3">
                <div className="mb-1.5 flex flex-wrap items-center gap-2 text-body-sm text-text-tertiary">
                  <span className="flex h-5 min-w-6 items-center justify-center rounded-sm bg-bg-subtle px-1 font-mono text-mono-sm text-text-secondary">
                    #{c.ordinal + 1}
                  </span>
                  {c.heading_path && <span className="min-w-0 truncate">{c.heading_path}</span>}
                  {formatPages(c.page_start, c.page_end) && <span className="font-mono text-mono-sm">{formatPages(c.page_start, c.page_end)}</span>}
                  {c.is_table && <Badge tone="neutral" icon={<Table aria-hidden />}>Table</Badge>}
                  <span className="ml-auto font-mono text-mono-sm">{formatNumber(c.token_count)} tok</span>
                </div>
                <p className="line-clamp-6 whitespace-pre-wrap break-words text-body text-text-primary">{c.text}</p>
              </li>
            ))}
            {chunks.length === 0 && <p className="py-6 text-center text-text-tertiary">No chunks match “{filter}”.</p>}
          </ol>
        )}
        {q.data && q.data.total > q.data.chunks.length && (
          <div className="flex items-center justify-center gap-3 pt-1 text-body-sm text-text-tertiary">
            Showing {formatNumber(q.data.chunks.length)} of {formatNumber(q.data.total)}
            <Button size="sm" loading={q.isFetching} onClick={() => setLimit((l) => l + 200)}>Load more</Button>
          </div>
        )}
      </div>
    </Dialog>
  )
}
