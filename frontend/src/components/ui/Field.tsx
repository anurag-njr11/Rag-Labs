import { useId, useState, type ReactNode } from 'react'
import { cn } from './cn'

export interface FieldProps {
  label: ReactNode
  /** Rendered next to the label (e.g. <EffectBadge effect="rebuild" />). */
  badge?: ReactNode
  help?: ReactNode
  /** Error message: replaces help, shown in danger-fg. */
  error?: ReactNode
  /** Right-aligned content on the label row (e.g. a Switch for toggle rows). */
  aside?: ReactNode
  /** Receives the generated control id + describedby id; wire them to your control. */
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode
  className?: string
  /** Put the control inline on the right of the label block (Toggle row layout). */
  inline?: boolean
  /** Optional explicit id for the control. */
  id?: string
  /** 'lg' = roomier label/help text for full-page editors (e.g. Configure). */
  size?: 'md' | 'lg'
  /** Help longer than this shows its first sentence + "More" (default 140). */
  helpLimit?: number
}

/**
 * Label + effect badge + control + help/error. Accessible: label `htmlFor`, `aria-describedby`, `aria-invalid`.
 *
 *   <Field label="Chunk size" badge={<EffectBadge effect="rebuild" />} help="…">
 *     {(f) => <Input id={f.id} aria-describedby={f.describedBy} invalid={f.invalid} />}
 *   </Field>
 */
/** Long help text shows its first sentence; the rest sits behind "More". */
const HELP_LIMIT = 140
function firstSentence(t: string, limit: number): string {
  const m = /^.{30,}?[.!?](?=\s)/.exec(t)
  return m && m[0].length < limit ? m[0] : t.slice(0, limit).replace(/\s+\S*$/, '') + '…'
}

export function Field({ label, badge, help, error, aside, children, className, inline, id: idProp, size = 'md', helpLimit = HELP_LIMIT }: FieldProps) {
  const auto = useId()
  const id = idProp ?? `f${auto}`
  const helpId = `${id}-help`
  const [open, setOpen] = useState(false)
  const hasHelp = !!(error || help)
  const ids = { id, describedBy: hasHelp ? helpId : undefined, invalid: !!error }
  const long = !error && typeof help === 'string' && help.length > helpLimit
  const helpEl = hasHelp && (
    <p id={helpId} className={cn(size === 'lg' ? 'text-body' : 'text-body-sm', error ? 'text-danger-fg' : 'text-text-tertiary')}>
      {long && !open ? firstSentence(help, helpLimit) : error || help}
      {long && (
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="focus-ring ml-1.5 rounded-sm text-accent-text hover:underline">
          {open ? 'Less' : 'More'}
        </button>
      )}
    </p>
  )

  if (inline) {
    return (
      <div className={cn('flex items-start justify-between gap-4', className)}>
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor={id} className={cn(size === 'lg' ? 'text-heading' : 'text-label', 'text-text-primary')}>{label}</label>
            {badge}
          </div>
          {helpEl}
        </div>
        <div className="shrink-0 pt-0.5">{children(ids)}</div>
      </div>
    )
  }
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <label htmlFor={id} className={cn(size === 'lg' ? 'text-heading' : 'text-label', 'text-text-primary')}>{label}</label>
          {badge}
        </div>
        {aside}
      </div>
      {children(ids)}
      {helpEl}
    </div>
  )
}
