import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { cn } from './cn'

export interface TabItem<V extends string = string> {
  value: V
  label: ReactNode
  icon?: ReactNode
  /** Small trailing count, e.g. 8. */
  count?: number
  disabled?: boolean
}

export interface TabsProps<V extends string = string> {
  items: TabItem<V>[]
  value: V
  onChange: (value: V) => void
  /** 'segment' (default) = panel sub-tabs/filters in a muted track; 'underline' = page-level tabs. */
  variant?: 'segment' | 'underline'
  size?: 'md' | 'sm'
  /** Accessible name for the tablist. */
  'aria-label'?: string
  className?: string
  /** Stretch items to fill the width (segment). */
  fill?: boolean
  /** id prefix: tab ids are `${idPrefix}-tab-${value}`, panels should use `${idPrefix}-panel-${value}`. */
  idPrefix?: string
}

/** Accessible tablist (arrow keys / Home / End). Render the panel yourself; use `tabPanelProps(idPrefix, value)`. */
export function Tabs<V extends string>({
  items, value, onChange, variant = 'segment', size = 'md', className, fill, idPrefix, ...aria
}: TabsProps<V>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const enabled = items.filter((i) => !i.disabled)

  const onKey = (e: KeyboardEvent) => {
    const idx = enabled.findIndex((i) => i.value === value)
    let next = -1
    if (e.key === 'ArrowRight') next = (idx + 1) % enabled.length
    else if (e.key === 'ArrowLeft') next = (idx - 1 + enabled.length) % enabled.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = enabled.length - 1
    if (next < 0) return
    e.preventDefault()
    const v = enabled[next].value
    onChange(v)
    refs.current[items.findIndex((i) => i.value === v)]?.focus()
  }

  const seg = variant === 'segment'
  return (
    <div
      role="tablist"
      aria-label={aria['aria-label']}
      onKeyDown={onKey}
      className={cn(
        seg ? 'inline-flex rounded-lg bg-bg-muted p-0.5' : 'flex gap-5 overflow-x-auto scrollbar-none',
        fill && 'flex w-full',
        className,
      )}
    >
      {items.map((it, i) => {
        const active = it.value === value
        return (
          <button
            key={it.value}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="tab"
            id={idPrefix ? `${idPrefix}-tab-${it.value}` : undefined}
            aria-controls={idPrefix ? `${idPrefix}-panel-${it.value}` : undefined}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            disabled={it.disabled}
            onClick={() => onChange(it.value)}
            className={cn(
              'focus-ring inline-flex items-center justify-center gap-1.5 whitespace-nowrap text-label transition-colors disabled:opacity-45 [&_svg]:size-3.5',
              seg
                ? cn(
                    'rounded-md px-3',
                    size === 'sm' ? 'h-6 text-body-sm' : 'h-7',
                    fill && 'flex-1',
                    active ? 'bg-bg-surface text-text-primary shadow-sm' : 'text-text-secondary hover:text-text-primary',
                  )
                : cn(
                    '-mb-px h-10 border-b-2 px-0.5',
                    active ? 'border-text-primary text-text-primary' : 'border-transparent text-text-secondary hover:text-text-primary',
                  ),
            )}
          >
            {it.icon}
            {it.label}
            {it.count != null && <span className="font-mono text-mono-sm text-text-tertiary">{it.count}</span>}
          </button>
        )
      })}
    </div>
  )
}

export const tabPanelProps = (idPrefix: string, value: string) => ({
  role: 'tabpanel' as const,
  id: `${idPrefix}-panel-${value}`,
  'aria-labelledby': `${idPrefix}-tab-${value}`,
  tabIndex: 0,
})

export interface TabLinkItem {
  to: string
  label: ReactNode
  icon?: ReactNode
  end?: boolean
}

/** Underline tabs that are router links (workspace navigation). Scrolls horizontally on mobile. */
export function TabLinks({ items, className, 'aria-label': ariaLabel }: { items: TabLinkItem[]; className?: string; 'aria-label'?: string }) {
  return (
    <nav aria-label={ariaLabel} className={cn('flex gap-5 overflow-x-auto scrollbar-none', className)}>
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.end}
          className={({ isActive }) =>
            cn(
              'focus-ring -mb-px inline-flex h-10 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-t-sm border-b-2 px-0.5 text-label transition-colors [&_svg]:size-3.5',
              isActive ? 'border-text-primary text-text-primary' : 'border-transparent text-text-secondary hover:text-text-primary',
            )
          }
        >
          {it.icon}
          {it.label}
        </NavLink>
      ))}
    </nav>
  )
}
