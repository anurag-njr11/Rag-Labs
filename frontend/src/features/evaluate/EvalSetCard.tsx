import { useState, type ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'
import type { EvalItem, EvalSetDetail } from '@/api/types'
import { Badge, Card, CardHeader, Disclosure, cn } from '@/components/ui'

const CELL = 'px-2 py-2 first:pl-4 last:pr-4 align-top'

function ItemRow({ item, n }: { item: EvalItem; n: number }) {
  const [open, setOpen] = useState(false)
  return (
    <tr className="border-b border-border-default last:border-b-0">
        <td className={cn(CELL, 'w-10 font-mono text-mono-sm text-text-tertiary')}>{n}</td>
        <td className={CELL}>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="focus-ring flex items-start gap-1.5 rounded-sm text-left text-body text-text-primary hover:text-accent-text"
          >
            <ChevronRight size={14} aria-hidden className={cn('mt-1 shrink-0 transition-transform', open && 'rotate-90')} />
            <span>{item.question}</span>
          </button>
          {open && (
            <dl className="mt-2 ml-5 grid gap-1.5 text-body-sm">
              <div>
                <dt className="inline text-text-tertiary">Answer: </dt>
                <dd className="inline text-text-primary">{item.gold_answer}</dd>
              </div>
              <div>
                <dt className="text-text-tertiary">Evidence (verbatim from the source):</dt>
                <dd className="mt-0.5 rounded-md border-l-2 border-accent-default bg-bg-subtle px-2 py-1 text-text-secondary">{item.evidence}</dd>
              </div>
              {item.closed_book_answer && (
                <div>
                  <dt className="inline text-text-tertiary">Model's answer with no documents: </dt>
                  <dd className="inline text-text-secondary">{item.closed_book_answer}</dd>
                </div>
              )}
            </dl>
          )}
        </td>
        <td className={cn(CELL, 'w-48 truncate text-body-sm text-text-secondary')} title={item.document ?? ''}>{item.document ?? '—'}</td>
        {!item.valid && (
          <td className={cn(CELL, 'w-64 text-body-sm text-warning-fg')}>{item.reject_reason}</td>
        )}
    </tr>
  )
}

function ItemTable({ items, rejected }: { items: EvalItem[]; rejected?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-left">
        <caption className="sr-only">{rejected ? 'Rejected questions' : 'Eval questions'}</caption>
        <thead>
          <tr className="h-9 border-b border-border-default bg-bg-subtle text-caption text-text-tertiary">
            <th scope="col" className={cn(CELL, 'py-0 font-medium')}>#</th>
            <th scope="col" className={cn(CELL, 'py-0 font-medium')}>Question</th>
            <th scope="col" className={cn(CELL, 'py-0 font-medium')}>Source</th>
            {rejected && <th scope="col" className={cn(CELL, 'py-0 font-medium')}>Why it was dropped</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => <ItemRow key={it.id} item={it} n={i + 1} />)}
        </tbody>
      </table>
    </div>
  )
}

export function EvalSetCard({ set, actions }: { set: EvalSetDetail; actions?: ReactNode }) {
  const kept = set.items.filter((i) => i.valid)
  const dropped = set.items.filter((i) => !i.valid)
  const st = set.stats
  return (
    <Card padding="none" className="overflow-hidden">
      <div className="p-4 pb-0">
        <CardHeader
          title="Eval set"
          description="Written from your own documents, then filtered: a question is dropped if the model can answer it without the documents, or if its evidence isn't really in the source."
          actions={actions}
        />
        <div className="mb-3 flex flex-wrap items-center gap-2 text-body-sm">
          <Badge tone="success">{kept.length} questions kept</Badge>
          {!!st.too_generic && <Badge tone="warning">{st.too_generic} too generic</Badge>}
          {!!st.bad_evidence && <Badge tone="warning">{st.bad_evidence} bad evidence</Badge>}
          <span className="text-text-tertiary">
            from {st.sampled ?? '—'} sampled chunks · 0 labelled by hand
          </span>
        </div>
      </div>
      <Disclosure label={`Questions (${kept.length})`} className="px-4" defaultOpen={false}>
        <div className="-mx-4">
          <ItemTable items={kept} />
        </div>
      </Disclosure>
      {dropped.length > 0 && (
        <Disclosure label={`Rejected by the filter (${dropped.length})`} className="px-4 pb-2">
          <div className="-mx-4">
            <ItemTable items={dropped} rejected />
          </div>
        </Disclosure>
      )}
    </Card>
  )
}
