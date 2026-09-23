import { LoaderCircle } from 'lucide-react'
import { cn } from './cn'

export interface SpinnerProps {
  size?: number
  className?: string
  /** Screen-reader label. Pass '' to hide (decorative). */
  label?: string
}

export function Spinner({ size = 16, className, label = 'Loading' }: SpinnerProps) {
  return (
    <LoaderCircle
      size={size}
      className={cn('animate-spin shrink-0', className)}
      role={label ? 'status' : undefined}
      aria-label={label || undefined}
      aria-hidden={label ? undefined : true}
    />
  )
}
