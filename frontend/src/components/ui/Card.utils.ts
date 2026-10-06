import { cn } from './cn'
import type { CardProps } from './Card'

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
