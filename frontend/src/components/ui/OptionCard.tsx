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
  /** Grid classes; default 1 → 2 → 3 columns. */
  className?: string
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
    <div role="radiogroup" aria-label={aria['aria-label']} onKeyDown={onKey} className={cn('grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3', className)}>
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
              'focus-ring flex h-full w-full flex-col gap-1.5 rounded-lg border p-3 text-left transition-[border-color,box-shadow,background-color]',
              selected
                ? 'border-accent-default bg-accent-subtle outline outline-[0.5px] outline-accent-default'
                : 'border-border-default bg-bg-surface',
              it.disabled ? 'cursor-not-allowed bg-bg-subtle' : !selected && 'hover:border-border-strong hover:shadow-md',
            )}
          >
            <div className="flex w-full items-center justify-between gap-2">
              <span className={cn('text-label', it.disabled ? 'text-text-disabled' : 'text-text-primary')}>{it.title}</span>
              <span
                aria-hidden
                className={cn(
                  'flex size-3.5 shrink-0 items-center justify-center rounded-full border',
                  selected ? 'border-accent-default' : 'border-border-strong',
                )}
              >
                {selected && <span className="size-1.5 rounded-full bg-accent-default" />}
              </span>
            </div>
            {it.description && (
              <span className={cn('text-body-sm', it.disabled ? 'text-text-disabled' : 'text-text-secondary')}>{it.description}</span>
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
  )
}
