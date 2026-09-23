import { useState, type ReactNode } from 'react'
import { ChevronRight, CircleCheck, CircleX, Info, TriangleAlert } from 'lucide-react'
import { cn } from './cn'

export interface EmptyStateProps {
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  /** Buttons. */
  actions?: ReactNode
  className?: string
}

/** Centered empty state (radius xl, dashed border). */
export function EmptyState({ icon, title, description, actions, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border-strong bg-bg-surface px-6 py-12 text-center',
        className,
      )}
    >
      {icon && (
        <div className="flex size-10 items-center justify-center rounded-lg bg-bg-subtle text-text-secondary [&_svg]:size-5">{icon}</div>
      )}
      <div className="max-w-md">
        <h3 className="text-heading text-text-primary">{title}</h3>
        {description && <p className="mt-1 text-body text-text-secondary">{description}</p>}
      </div>
      {actions && <div className="mt-1 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  )
}

export type BannerTone = 'warning' | 'danger' | 'info' | 'success'
const bannerTone: Record<BannerTone, { cls: string; icon: ReactNode }> = {
  warning: { cls: 'bg-warning-bg border-warning-border text-warning-fg', icon: <TriangleAlert aria-hidden /> },
  danger: { cls: 'bg-danger-bg border-danger-border text-danger-fg', icon: <CircleX aria-hidden /> },
  info: { cls: 'bg-info-bg border-info-border text-info-fg', icon: <Info aria-hidden /> },
  success: { cls: 'bg-success-bg border-success-border text-success-fg', icon: <CircleCheck aria-hidden /> },
}

export interface BannerProps {
  tone?: BannerTone
  /** Bold lead-in in the tone colour. */
  title?: ReactNode
  children?: ReactNode
  /** Right-side actions. */
  actions?: ReactNode
  /** 'bar' = full-width strip with a bottom border (page level); 'inline' = rounded box (default). */
  variant?: 'inline' | 'bar'
  icon?: ReactNode
  className?: string
}

/** Tone banner (warnings, errors). Text stays text-primary for contrast; icon + title use the tone colour. */
export function Banner({ tone = 'warning', title, children, actions, variant = 'inline', icon, className }: BannerProps) {
  const t = bannerTone[tone]
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={cn(
        'flex items-start gap-2.5 text-body [&>svg]:size-4',
        t.cls,
        variant === 'bar' ? 'min-h-10 border-b px-4 py-2.5 sm:px-8' : 'rounded-lg border p-3',
        className,
      )}
    >
      <span className="mt-0.5 shrink-0 [&_svg]:size-4">{icon ?? t.icon}</span>
      <div className="min-w-0 flex-1 text-text-primary">
        {title && <span className="mr-1 text-label" style={{ color: 'inherit' }}>{title}</span>}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

export interface DisclosureProps {
  label: ReactNode
  /** Right-side hint, e.g. "3 more". */
  hint?: ReactNode
  defaultOpen?: boolean
  open?: boolean
  onOpenChange?: (open: boolean) => void
  children: ReactNode
  className?: string
}

/** Chevron + label disclosure row (e.g. "Advanced · 3 more"), bottom-bordered. */
export function Disclosure({ label, hint, defaultOpen = false, open: openProp, onOpenChange, children, className }: DisclosureProps) {
  const [inner, setInner] = useState(defaultOpen)
  const open = openProp ?? inner
  const toggle = () => {
    setInner(!open)
    onOpenChange?.(!open)
  }
  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        onClick={toggle}
        className="focus-ring flex w-full items-center gap-1.5 rounded-sm border-b border-border-default py-2 text-left text-label text-text-secondary hover:text-text-primary"
      >
        <ChevronRight size={14} aria-hidden className={cn('transition-transform', open && 'rotate-90')} />
        {label}
        {hint && <span className="text-body-sm text-text-tertiary">{hint}</span>}
      </button>
      {open && <div className="pt-4">{children}</div>}
    </div>
  )
}

/** Visually-hidden text for screen readers. */
export const VisuallyHidden = ({ children }: { children: ReactNode }) => <span className="sr-only">{children}</span>
