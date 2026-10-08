import { cn } from './cn'
import type { ButtonSize, ButtonVariant } from './Button'

const base =
  'focus-ring inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors select-none ' +
  'disabled:opacity-45 disabled:pointer-events-none aria-disabled:opacity-45 aria-disabled:pointer-events-none'

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-accent-default text-text-inverse hover:bg-accent-hover shadow-sm ' +
    'disabled:bg-bg-muted disabled:text-text-tertiary disabled:opacity-100 disabled:shadow-none',
  secondary: 'bg-bg-surface text-text-primary border border-border-strong hover:bg-bg-subtle shadow-sm',
  ghost: 'bg-transparent text-text-secondary hover:bg-bg-subtle hover:text-text-primary',
  danger: 'bg-danger-fg text-white hover:opacity-90 dark:text-text-inverse shadow-sm',
}

export function buttonClasses({
  variant = 'secondary',
  size = 'md',
  iconOnly = false,
  className,
}: { variant?: ButtonVariant; size?: ButtonSize; iconOnly?: boolean; className?: string } = {}) {
  const sizing = iconOnly
    ? size === 'sm' ? 'size-6' : 'size-8'
    : size === 'sm' ? 'h-6 px-2 text-body-sm' : 'h-8 px-3 text-label'
  return cn(base, variants[variant], sizing, className)
}
