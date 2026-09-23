import type { ComponentProps, ReactNode } from 'react'
import { FileText } from 'lucide-react'
import { cn } from './cn'

export interface CitationChipProps extends Omit<ComponentProps<'button'>, 'children'> {
  n: number
  active?: boolean
}

/** Inline `[n]` citation chip (18px mono, accent-subtle). Clicking should scroll the Inspector to source n. */
export function CitationChip({ n, active, className, ...rest }: CitationChipProps) {
  return (
    <button
      type="button"
      aria-label={`Source ${n}`}
      className={cn(
        'focus-ring mx-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-sm border px-1 align-[1px] font-mono text-mono-sm transition-colors',
        active
          ? 'border-accent-default bg-accent-default text-text-inverse'
          : 'border-accent-border bg-accent-subtle text-accent-text hover:border-accent-default',
        className,
      )}
      {...rest}
    >
      {n}
    </button>
  )
}

export interface SourceChipProps extends Omit<ComponentProps<'button'>, 'children'> {
  document: string
  /** e.g. "p.4" */
  meta?: string
}

/** Source chip: file icon + "models.md · p.4". */
export function SourceChip({ document, meta, className, ...rest }: SourceChipProps) {
  return (
    <button
      type="button"
      className={cn(
        'focus-ring inline-flex h-6 max-w-full items-center gap-1.5 rounded-md border border-border-default bg-bg-surface px-2 text-body-sm text-text-secondary hover:border-border-strong hover:text-text-primary',
        className,
      )}
      {...rest}
    >
      <FileText size={12} aria-hidden className="shrink-0" />
      <span className="truncate">{document}</span>
      {meta && <span className="shrink-0 text-text-tertiary">· {meta}</span>}
    </button>
  )
}

export interface PillProps extends ComponentProps<'span'> {
  icon?: ReactNode
  /** Leading status dot colour class, e.g. "bg-success-fg". */
  dotClassName?: string
}

/** Header metadata pill ("v3 · active", "Index ready · 517 chunks · FAISS"). */
export function Pill({ icon, dotClassName, className, children, ...rest }: PillProps) {
  return (
    <span
      className={cn(
        'inline-flex h-6 max-w-full items-center gap-1.5 whitespace-nowrap rounded-full border border-border-default bg-bg-surface px-2.5 text-body-sm text-text-secondary [&_svg]:size-3.5 [&_svg]:shrink-0',
        className,
      )}
      {...rest}
    >
      {dotClassName && <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', dotClassName)} />}
      {icon}
      <span className="truncate">{children}</span>
    </span>
  )
}
