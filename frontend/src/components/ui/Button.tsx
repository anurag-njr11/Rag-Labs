import type { ComponentProps, ReactNode } from 'react'
import { Link, type LinkProps } from 'react-router-dom'
import { cn } from './cn'
import { Spinner } from './Spinner'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'md' | 'sm'

interface CommonProps {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Leading icon element, e.g. <Upload size={14} />. */
  icon?: ReactNode
  /** Trailing icon element. */
  iconRight?: ReactNode
  /** Shows a spinner in place of the icon and disables the button. */
  loading?: boolean
  /** Icon-only square button — requires `aria-label`. */
  iconOnly?: boolean
}

const base =
  'focus-ring inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors select-none ' +
  'disabled:opacity-45 disabled:pointer-events-none aria-disabled:opacity-45 aria-disabled:pointer-events-none'

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-accent-default text-text-inverse hover:bg-accent-hover shadow-sm',
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

export type ButtonProps = CommonProps & ComponentProps<'button'>

export function Button({
  variant = 'secondary', size = 'md', icon, iconRight, loading, iconOnly, className, children, disabled, type = 'button', ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, iconOnly, className })}
      {...rest}
    >
      {loading ? <Spinner size={size === 'sm' ? 12 : 14} label="" /> : icon}
      {children}
      {iconRight}
    </button>
  )
}

export type ButtonLinkProps = CommonProps & LinkProps

/** A react-router Link styled as a button. */
export function ButtonLink({ variant = 'secondary', size = 'md', icon, iconRight, iconOnly, className, children, ...rest }: ButtonLinkProps) {
  return (
    <Link className={buttonClasses({ variant, size, iconOnly, className })} {...rest}>
      {icon}
      {children}
      {iconRight}
    </Link>
  )
}
