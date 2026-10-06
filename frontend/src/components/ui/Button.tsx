import type { ComponentProps, ReactNode } from 'react'
import { Link, type LinkProps } from 'react-router-dom'
import { Spinner } from './Spinner'
import { buttonClasses } from './Button.utils'

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
