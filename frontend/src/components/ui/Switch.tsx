import type { ComponentProps } from 'react'
import { cn } from './cn'

export interface SwitchProps extends Omit<ComponentProps<'button'>, 'onChange' | 'value'> {
  checked: boolean
  onChange: (checked: boolean) => void
}

/** 28×16 switch (role="switch"). Pair it with a label via `id` + <label htmlFor> or `aria-label`. */
export function Switch({ checked, onChange, className, disabled, ...rest }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'focus-ring relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors disabled:opacity-45',
        checked ? 'bg-accent-default' : 'bg-border-strong',
        className,
      )}
      {...rest}
    >
      <span
        aria-hidden
        className={cn(
          'inline-block size-3 rounded-full bg-white shadow-sm transition-transform',
          checked ? 'translate-x-[14px]' : 'translate-x-0.5',
        )}
      />
    </button>
  )
}

/** Alias: the design calls the switch row a "Toggle". */
export const Toggle = Switch
