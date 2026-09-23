import type { ComponentProps, ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from './cn'

const control =
  'w-full rounded-md border bg-bg-surface text-body text-text-primary placeholder:text-text-tertiary transition-[border-color,box-shadow] ' +
  'outline-none focus-visible:border-border-focus focus-visible:shadow-[var(--shadow-focus)] ' +
  'disabled:cursor-not-allowed disabled:bg-bg-subtle disabled:text-text-disabled'

const border = (invalid?: boolean) =>
  invalid ? 'border-danger-fg focus-visible:border-danger-fg' : 'border-border-strong'

export interface InputProps extends Omit<ComponentProps<'input'>, 'size'> {
  /** Leading icon element (14px). */
  icon?: ReactNode
  /** Trailing text/element, e.g. "chars". */
  suffix?: ReactNode
  invalid?: boolean
  /** Monospace value (numbers, URLs, IDs). */
  mono?: boolean
  size?: 'md' | 'sm'
  /** Class for the outer wrapper (width etc.). `className` applies to the <input>. */
  wrapperClassName?: string
}

/** 32px text input (24px for size="sm"). */
export function Input({ icon, suffix, invalid, mono, size = 'md', className, wrapperClassName, ...rest }: InputProps) {
  return (
    <div className={cn('relative flex items-center', wrapperClassName)}>
      {icon && (
        <span aria-hidden className="pointer-events-none absolute left-2.5 flex text-text-tertiary [&_svg]:size-3.5">
          {icon}
        </span>
      )}
      <input
        aria-invalid={invalid || undefined}
        className={cn(
          control,
          border(invalid),
          size === 'sm' ? 'h-6 px-2 text-body-sm' : 'h-8 px-2.5',
          icon && 'pl-8',
          suffix && 'pr-12',
          mono && 'font-mono text-mono',
          className,
        )}
        {...rest}
      />
      {suffix && (
        <span className="pointer-events-none absolute right-2.5 text-body-sm text-text-tertiary">{suffix}</span>
      )}
    </div>
  )
}

export interface TextareaProps extends ComponentProps<'textarea'> {
  invalid?: boolean
  mono?: boolean
}

export function Textarea({ invalid, mono, className, rows = 4, ...rest }: TextareaProps) {
  return (
    <textarea
      rows={rows}
      aria-invalid={invalid || undefined}
      className={cn(control, border(invalid), 'resize-y px-2.5 py-1.5', mono && 'font-mono text-mono', className)}
      {...rest}
    />
  )
}

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface SelectProps extends Omit<ComponentProps<'select'>, 'size'> {
  options: SelectOption[]
  invalid?: boolean
  size?: 'md' | 'sm'
  /** Shown as a disabled first option when value is ''. */
  placeholder?: string
  wrapperClassName?: string
}

/** Native select styled as the design's Select (trailing chevron). */
export function Select({ options, invalid, size = 'md', placeholder, className, wrapperClassName, ...rest }: SelectProps) {
  return (
    <div className={cn('relative flex items-center', wrapperClassName)}>
      <select
        aria-invalid={invalid || undefined}
        className={cn(control, border(invalid), 'appearance-none pr-8', size === 'sm' ? 'h-6 pl-2 text-body-sm' : 'h-8 pl-2.5', className)}
        {...rest}
      >
        {placeholder !== undefined && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown aria-hidden size={14} className="pointer-events-none absolute right-2.5 text-text-tertiary" />
    </div>
  )
}

export interface ComboboxProps extends Omit<InputProps, 'list' | 'onChange' | 'value'> {
  value: string
  onChange: (value: string) => void
  /** Suggestions; free text is always allowed. */
  options: string[]
  loading?: boolean
}

/** Free-text input with suggestions (native datalist) — for `options_from` model pickers. */
export function Combobox({ value, onChange, options, loading, id, ...rest }: ComboboxProps) {
  const listId = `${id ?? 'cb'}-list`
  return (
    <>
      <Input
        id={id}
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        suffix={loading ? '…' : rest.suffix}
        {...rest}
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </>
  )
}
