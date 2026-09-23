import { useState } from 'react'
import { cn } from './cn'

export interface SliderProps {
  value: number
  onChange: (value: number) => void
  min: number
  max: number
  /** Default: 1 for integers, else (max-min)/100. */
  step?: number
  integer?: boolean
  /** Unit shown after the numeric input ("chars", "tokens"). */
  unit?: string
  id?: string
  disabled?: boolean
  invalid?: boolean
  'aria-describedby'?: string
  /** Hide min/max labels under the track. */
  hideBounds?: boolean
  className?: string
}

const fmt = (n: number) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 }).format(n)

/**
 * Range slider + 72px mono numeric input (Field/Slider). The number input accepts values
 * outside the slider only within [min, max]; it commits on blur/Enter.
 * `id` goes on the numeric input (so <label htmlFor> focuses it); the range gets `${id}-range`.
 */
export function Slider({
  value, onChange, min, max, step, integer, unit, id, disabled, invalid, hideBounds, className, ...aria
}: SliderProps) {
  const s = step ?? (integer ? 1 : (max - min) / 100)
  /** null = not editing → show `value`. */
  const [draft, setDraft] = useState<string | null>(null)

  const commit = () => {
    if (draft === null) return
    const n = Number(draft)
    setDraft(null)
    if (draft.trim() === '' || Number.isNaN(n)) return
    let v = Math.min(max, Math.max(min, n))
    if (integer) v = Math.round(v)
    if (v !== value) onChange(v)
  }
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div className="flex items-center gap-3">
        <input
          type="range"
          id={id ? `${id}-range` : undefined}
          aria-label="Adjust value"
          aria-describedby={aria['aria-describedby']}
          min={min}
          max={max}
          step={s}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(integer ? Math.round(Number(e.target.value)) : Number(e.target.value))}
          style={{ background: `linear-gradient(to right, var(--color-accent-default) ${pct}%, var(--color-bg-muted) ${pct}%)` }}
          className={cn(
            'h-1 min-w-0 flex-1 cursor-pointer appearance-none rounded-full outline-none disabled:opacity-45',
            '[&::-webkit-slider-thumb]:size-3.5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-border-strong [&::-webkit-slider-thumb]:bg-bg-surface [&::-webkit-slider-thumb]:shadow-sm',
            '[&::-moz-range-thumb]:size-3.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border [&::-moz-range-thumb]:border-border-strong [&::-moz-range-thumb]:bg-bg-surface',
            'focus-visible:[&::-webkit-slider-thumb]:shadow-[0_0_0_1px_var(--color-border-focus),var(--shadow-focus)]',
          )}
        />
        <div className="flex shrink-0 items-center gap-1.5">
          <input
            id={id}
            type="number"
            inputMode={integer ? 'numeric' : 'decimal'}
            min={min}
            max={max}
            step={s}
            value={draft ?? String(value)}
            disabled={disabled}
            aria-invalid={invalid || undefined}
            aria-describedby={aria['aria-describedby']}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit()
            }}
            className={cn(
              'h-8 w-[72px] rounded-md border bg-bg-surface px-2 text-right font-mono text-mono text-text-primary outline-none',
              'focus-visible:border-border-focus focus-visible:shadow-[var(--shadow-focus)] disabled:opacity-45',
              invalid ? 'border-danger-fg' : 'border-border-strong',
            )}
          />
          {unit && <span className="text-body-sm text-text-tertiary">{unit}</span>}
        </div>
      </div>
      {!hideBounds && (
        <div className="flex justify-between pr-[calc(72px+0.75rem)] font-mono text-mono-sm text-text-tertiary" aria-hidden>
          <span>{fmt(min)}</span>
          <span>{fmt(max)}</span>
        </div>
      )}
    </div>
  )
}
