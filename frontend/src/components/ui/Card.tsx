import type { ComponentProps, ReactNode } from 'react'
import { cn } from './cn'

export interface CardProps extends ComponentProps<'div'> {
  /** Hover: border-strong + shadow-md. */
  interactive?: boolean
  /** Accent border 1.5px + accent-subtle background. */
  selected?: boolean
  /** Padding: none | sm (12px) | md (16px, default) | lg (20px). */
  padding?: 'none' | 'sm' | 'md' | 'lg'
}

const pad = { none: '', sm: 'p-3', md: 'p-4', lg: 'p-5' }

export function cardClasses({ interactive, selected, padding = 'md', className }: Omit<CardProps, 'children'> = {}) {
  return cn(
    'rounded-lg border shadow-sm transition-[border-color,box-shadow,background-color]',
    selected ? 'border-accent-default bg-accent-subtle outline outline-[0.5px] outline-accent-default' : 'border-border-default bg-bg-surface',
    interactive && !selected && 'hover:border-border-strong hover:shadow-md',
    pad[padding],
    className,
  )
}

export function Card({ interactive, selected, padding = 'md', className, ...rest }: CardProps) {
  return <div className={cardClasses({ interactive, selected, padding, className })} {...rest} />
}

/** Card header row: title (+ optional description) on the left, actions on the right. */
export function CardHeader({
  title, description, actions, className,
}: { title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn('mb-4 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0">
        <h2 className="text-title text-text-primary">{title}</h2>
        {description && <p className="mt-0.5 text-body text-text-secondary">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
