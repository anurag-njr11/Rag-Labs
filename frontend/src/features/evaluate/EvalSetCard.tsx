import { useState, type ReactNode } from 'react'
import { ChevronRight, FileText } from 'lucide-react'
import type { EvalItem, EvalSetDetail } from '@/api/types'
import { Badge, Card, Disclosure, cn } from '@/components/ui'

/** One eval question as an expandable list row (fits the narrow side panel). */
function ItemRow({ item, n }: { item: EvalItem; n: number }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="border-b border-border-default last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="focus-ring flex w-full items-start gap-2.5 rounded-md px-1 py-2.5 text-left hover:bg-bg-subtle"
      >
        <span className="mt-0.5 w-5 shrink-0 text-right font-mono text-mono-sm text-text-tertiary">{n}</span>
        <span className="min-w-0 flex-1 text-body text-text-primary">{item.question}</span>
        <ChevronRight size={14} aria-hidden className={cn('mt-1 shrink-0 text-text-tertiary transition-transform', open && 'rotate-90')} />
      </button>
      {open && (
        <dl className="mb-3 ml-8 mr-1 grid gap-2 text-body-sm">
          {item.document && (
            <div className="flex items-center gap-1.5 text-text-tertiary">
              <FileText size={12} aria-hidden className="shrink-0" />
              <span className="truncate" title={item.document}>{item.document}</span>
            </div>
          )}
          <div>
            <dt className="text-text-tertiary">Answer</dt>
            <dd className="text-text-primary">{item.gold_answer}</dd>
          </div>
          <div>
            <dt className="text-text-tertiary">Evidence (verbatim from the source)</dt>
            <dd className="mt-0.5 rounded-md border-l-2 border-accent-default bg-bg-subtle px-2 py-1 text-text-secondary">{item.evidence}</dd>
          </div>
          {item.closed_book_answer && (
            <div>
              <dt className="text-text-tertiary">Model's answer with no documents</dt>
              <dd className="text-text-secondary">{item.closed_book_answer}</dd>
            </div>
          )}
          {!item.valid && item.reject_reason && (
            <div>
              <dt className="text-text-tertiary">Why it was dropped</dt>
              <dd className="text-warning-fg">{item.reject_reason}</dd>
            </div>
          )}
        </dl>
      )}
    </li>
  )
}

function ItemList({ items, label }: { items: EvalItem[]; label: string }) {
  return (
    <ol aria-label={label} className="mt-1">
      {items.map((it, i) => <ItemRow key={it.id} item={it} n={i + 1} />)}
    </ol>
  )
}

/** Eval set summary for the Evaluate side panel: size, filter stats, regenerate controls, question list. */
export function EvalSetCard({
  set, actions, progress, compact,
}: {
  set: EvalSetDetail
  actions?: ReactNode
  progress?: ReactNode
  /** Rail variant: shorter copy, and no kept-question list (the per-question results already show them). */
  compact?: boolean
}) {
  const kept = set.items.filter((i) => i.valid)
  const dropped = set.items.filter((i) => !i.valid)
  const st = set.stats
  return (
    <Card padding="lg" className="flex flex-col gap-4">
      <div>
        <h2 className="text-heading-lg text-text-primary">Eval set</h2>
        <p className="mt-1 text-body text-text-secondary">
          {compact
            ? 'Questions written from your documents; ones a model can answer without them are dropped.'
            : "Written from your own documents, then filtered: a question is dropped if the model can answer it without the documents, or if its evidence isn't really in the source."}
        </p>
      </div>

      <div className="flex items-end gap-3 rounded-lg bg-bg-subtle px-4 py-3">
        <span className="font-mono text-display tabular-nums text-text-primary">{kept.length}</span>
        <span className="pb-1 text-body text-text-secondary">
          questions kept
          <span className="block text-body-sm text-text-tertiary">
            from {st.sampled ?? '—'} sampled chunks · 0 labelled by hand
          </span>
        </span>
      </div>

      {(!!st.too_generic || !!st.bad_evidence) && (
        <div className="flex flex-wrap gap-2">
          {!!st.too_generic && <Badge tone="warning">{st.too_generic} too generic</Badge>}
          {!!st.bad_evidence && <Badge tone="warning">{st.bad_evidence} bad evidence</Badge>}
        </div>
      )}

      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      {progress}

      {(!compact || dropped.length > 0) && (
        <div className="-mx-1 border-t border-border-default pt-2">
          {!compact && (
            <Disclosure label={`Questions (${kept.length})`} className="px-1">
              <ItemList items={kept} label="Eval questions" />
            </Disclosure>
          )}
          {dropped.length > 0 && (
            <Disclosure label={`Rejected by the filter (${dropped.length})`} className="px-1">
              <ItemList items={dropped} label="Rejected questions" />
            </Disclosure>
          )}
        </div>
      )}
    </Card>
  )
}
