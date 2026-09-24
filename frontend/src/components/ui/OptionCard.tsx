import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { Lock } from 'lucide-react'
import { cn } from './cn'
import { Tooltip } from './Popover'

export interface OptionCardItem<V extends string = string> {
  value: V
  title: ReactNode
  description?: ReactNode
  /** Badges row (e.g. <ExactBadge exact />, <Badge>Local</Badge>). */
  badges?: ReactNode
  disabled?: boolean
  /** Shown with a lock when disabled, e.g. "Add NVIDIA_API_KEY to .env". */
  reason?: ReactNode
}

export interface OptionCardGroupProps<V extends string = string> {
  items: OptionCardItem<V>[]
  value: V | null | undefined
  onChange: (value: V) => void
  'aria-label': string
  /** Grid classes; default picks columns from the option count so rows fill evenly (see `evenCols`). */
  className?: string
}

/**
 * Column classes keyed by option count, via container queries on the group itself, so every row is full
 * (4 options → 2×2 or 4 across, never 3 + 1 orphan).
 */
function evenCols(n: number) {
  if (n <= 1) return 'grid-cols-1'
  if (n === 2) return 'grid-cols-1 @min-[480px]:grid-cols-2'
  if (n === 3 || n === 6 || n === 5) return 'grid-cols-1 @min-[480px]:grid-cols-2 @min-[720px]:grid-cols-3'
  return 'grid-cols-1 @min-[480px]:grid-cols-2 @min-[960px]:grid-cols-4'
}

/**
 * Radio-card group (Card/Option). Arrow keys move between enabled options; disabled options show
 * a lock + reason and can't be selected (hover shows the reason as a tooltip).
 */
export function OptionCardGroup<V extends string>({ items, value, onChange, className, ...aria }: OptionCardGroupProps<V>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const enabled = items.filter((i) => !i.disabled)
  const focusValue = enabled.some((i) => i.value === value) ? value : enabled[0]?.value

  const onKey = (e: KeyboardEvent) => {
    const keys = ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp']
    if (!keys.includes(e.key) || !enabled.length) return
    e.preventDefault()
    const idx = enabled.findIndex((i) => i.value === focusValue)
    const dir = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : -1
    const next = enabled[(idx + dir + enabled.length) % enabled.length]
    onChange(next.value)
    refs.current[items.indexOf(next)]?.focus()
  }

  return (
    <div className="@container">
      <div role="radiogroup" aria-label={aria['aria-label']} onKeyDown={onKey} className={cn('grid gap-3', className ?? evenCols(items.length))}>
        {items.map((it, i) => {
          const selected = it.value === value
          const card = (
            <button
              key={it.value}
              ref={(el) => {
                refs.current[i] = el
              }}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-disabled={it.disabled || undefined}
              tabIndex={it.disabled ? -1 : it.value === focusValue ? 0 : -1}
              onClick={() => !it.disabled && onChange(it.value)}
              className={cn(
                'focus-ring flex h-full w-full flex-col gap-2 rounded-xl border p-4 text-left transition-[border-color,box-shadow,background-color]',
                selected
                  ? 'border-accent-default bg-accent-subtle outline outline-[0.5px] outline-accent-default'
                  : 'border-border-default bg-bg-surface',
                it.disabled ? 'cursor-not-allowed bg-bg-subtle' : !selected && 'hover:border-border-strong hover:shadow-md',
              )}
            >
              <div className="flex w-full items-center justify-between gap-2">
                <span className={cn('text-heading-lg', it.disabled ? 'text-text-disabled' : 'text-text-primary')}>{it.title}</span>
                <span
                  aria-hidden
                  className={cn(
                    'flex size-[18px] shrink-0 items-center justify-center rounded-full border-[1.5px]',
                    selected ? 'border-accent-default' : 'border-border-strong',
                  )}
                >
                  {selected && <span className="size-2 rounded-full bg-accent-default" />}
                </span>
              </div>
              {it.description && (
                <span className={cn('text-body-lg', it.disabled ? 'text-text-disabled' : 'text-text-secondary')}>{it.description}</span>
              )}
              {it.badges && <span className="flex flex-wrap gap-1">{it.badges}</span>}
              {it.disabled && it.reason && (
                <span className="flex items-center gap-1 text-body-sm text-text-tertiary">
                  <Lock size={12} aria-hidden className="shrink-0" />
                  {it.reason}
                </span>
              )}
            </button>
          )
          return it.disabled && it.reason ? (
            <Tooltip key={it.value} content={it.reason}>
              {card}
            </Tooltip>
          ) : (
            card
          )
        })}
      </div>
    </div>
  )
}
