import { useEffect, useId, useLayoutEffect, useRef, useState, type ComponentProps, type KeyboardEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from './cn'
import { useFloating } from './useFloating'

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

/** Long "Name · detail · detail" labels → the name, and the details for a second, muted line. */
const splitLabel = (label: string): [string, string] => {
  const i = label.indexOf(' · ')
  return i > 0 && label.length > 36 ? [label.slice(0, i), label.slice(i + 3)] : [label, '']
}
function OptionText({ label }: { label: string }) {
  const [name, detail] = splitLabel(label)
  return (
    <span className="flex min-w-0 flex-1 flex-col">
      <span className="break-words">{name}</span>
      {detail && <span className="break-words text-body-sm text-text-tertiary">{detail}</span>}
    </span>
  )
}

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface SelectProps extends Omit<ComponentProps<'button'>, 'size' | 'value' | 'defaultValue' | 'onChange'> {
  options: SelectOption[]
  value?: string
  defaultValue?: string
  /** Called like a native select's: `e.target.value` is the chosen option. */
  onChange?: (e: { target: { value: string }; currentTarget: { value: string } }) => void
  invalid?: boolean
  size?: 'md' | 'sm'
  /** Shown when value is ''. */
  placeholder?: string
  wrapperClassName?: string
}

/**
 * Styled select: a button that opens a listbox (the browser's own list can't be themed). Arrow keys / Home / End /
 * type-ahead move, Enter or Space picks, Esc closes. Same props as before, so `onChange={(e) => … e.target.value}` still works.
 */
export function Select({
  options, invalid, size = 'md', placeholder, className, wrapperClassName, value: valueProp, defaultValue = '', onChange, disabled, id, ...rest
}: SelectProps) {
  const [inner, setInner] = useState(defaultValue)
  const value = valueProp ?? inner
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [width, setWidth] = useState(0)
  const [host, setHost] = useState<HTMLElement | null>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const auto = useId()
  const listId = `${id ?? auto}-list`
  const typed = useRef({ s: '', t: 0 })
  const pos = useFloating(open, trigger, list, 'bottom', 'start')
  const selected = options.find((o) => o.value === value)

  const choose = (o: SelectOption) => {
    if (o.disabled) return
    setInner(o.value)
    onChange?.({ target: { value: o.value }, currentTarget: { value: o.value } })
    setOpen(false)
    trigger.current?.focus()
  }
  const openList = () => {
    const i = options.findIndex((o) => o.value === value)
    setActive(i >= 0 ? i : Math.max(0, options.findIndex((o) => !o.disabled)))
    setWidth(trigger.current?.offsetWidth ?? 0)
    setHost(trigger.current?.closest('dialog') ?? document.body) // a modal <dialog> makes everything outside it inert
    setOpen(true)
  }
  const step = (from: number, dir: 1 | -1) => {
    for (let i = from + dir; i >= 0 && i < options.length; i += dir) if (!options[i].disabled) return i
    return from
  }

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!list.current?.contains(t) && !trigger.current?.contains(t)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])
  useLayoutEffect(() => {
    if (open) list.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) { e.preventDefault(); openList() }
      return
    }
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false) }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => step(a, 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => step(a, -1)) }
    else if (e.key === 'Home') { e.preventDefault(); setActive(step(-1, 1)) }
    else if (e.key === 'End') { e.preventDefault(); setActive(step(options.length, -1)) }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (options[active]) choose(options[active]) }
    else if (e.key === 'Tab') setOpen(false)
    else if (e.key.length === 1) { // type-ahead
      const now = Date.now()
      typed.current.s = now - typed.current.t > 700 ? e.key.toLowerCase() : typed.current.s + e.key.toLowerCase()
      typed.current.t = now
      const i = options.findIndex((o) => !o.disabled && o.label.toLowerCase().startsWith(typed.current.s))
      if (i >= 0) setActive(i)
    }
  }

  return (
    <div className={cn('relative flex items-center', wrapperClassName)}>
      <button
        ref={trigger}
        type="button"
        id={id}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        aria-invalid={invalid || undefined}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={onKey}
        className={cn(control, border(invalid), 'flex items-center pr-8 text-left', size === 'sm' ? 'h-6 pl-2 text-body-sm' : 'h-8 pl-2.5', className)}
        {...rest}
      >
        <span className={cn('truncate', !selected && 'text-text-tertiary')}>{selected?.label ?? placeholder ?? ''}</span>
      </button>
      <ChevronDown aria-hidden size={14} className={cn('pointer-events-none absolute right-2.5 text-text-tertiary transition-transform', open && 'rotate-180')} />
      {open && host && createPortal(
        <ul
          ref={list}
          id={listId}
          role="listbox"
          style={{ position: 'fixed', top: pos?.top ?? -9999, left: pos?.left ?? -9999, width, maxWidth: 'calc(100vw - 16px)' }}
          className="z-[70] max-h-72 overflow-x-hidden overflow-y-auto rounded-lg border border-border-default bg-bg-surface py-1 text-body shadow-lg"
        >
          {options.map((o, i) => (
            <li
              key={o.value}
              id={`${listId}-${i}`}
              data-i={i}
              role="option"
              aria-selected={o.value === value}
              aria-disabled={o.disabled || undefined}
              onMouseEnter={() => !o.disabled && setActive(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(o)}
              className={cn(
                'flex min-h-8 cursor-pointer items-center gap-2 px-2.5 py-1.5',
                i === active && 'bg-bg-subtle',
                o.value === value ? 'text-accent-text' : 'text-text-primary',
                o.disabled && 'cursor-not-allowed text-text-disabled',
              )}
            >
              <OptionText label={o.label} />
              {o.value === value && <Check size={14} aria-hidden className="shrink-0" />}
            </li>
          ))}
        </ul>,
        host,
      )}
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

/** Free-text input with a styled suggestion list (filters as you type; Arrow keys + Enter pick; Esc closes). */
export function Combobox({ value, onChange, options, loading, id, onFocus, onKeyDown, ...rest }: ComboboxProps) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [width, setWidth] = useState(0)
  const [host, setHost] = useState<HTMLElement | null>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const auto = useId()
  const listId = `${id ?? auto}-list`
  const pos = useFloating(open, wrap, list, 'bottom', 'start')
  const q = value.trim().toLowerCase()
  const shown = (q && !options.includes(value) ? options.filter((o) => o.toLowerCase().includes(q)) : options).slice(0, 60)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!list.current?.contains(t) && !wrap.current?.contains(t)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])
  useLayoutEffect(() => {
    if (open && active >= 0) list.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  const pick = (o: string) => { onChange(o); setOpen(false); setActive(-1) }
  const visible = open && shown.length > 0
  return (
    <div ref={wrap}>
      <Input
        id={id}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={visible}
        aria-controls={visible ? listId : undefined}
        aria-activedescendant={visible && active >= 0 ? `${listId}-${active}` : undefined}
        value={value}
        onChange={(e) => { onChange(e.target.value); setWidth(wrap.current?.offsetWidth ?? 0); setHost(wrap.current?.closest('dialog') ?? document.body); setOpen(true); setActive(-1) }}
        onFocus={(e) => { setWidth(wrap.current?.offsetWidth ?? 0); setHost(wrap.current?.closest('dialog') ?? document.body); setOpen(true); onFocus?.(e) }}
        onKeyDown={(e) => {
          onKeyDown?.(e)
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(shown.length - 1, a + 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
          else if (e.key === 'Enter' && visible && active >= 0) { e.preventDefault(); pick(shown[active]) }
          else if (e.key === 'Escape' && visible) { e.stopPropagation(); setOpen(false) }
          else if (e.key === 'Tab') setOpen(false)
        }}
        autoComplete="off"
        suffix={loading ? '…' : rest.suffix}
        {...rest}
      />
      {visible && host && createPortal(
        <ul
          ref={list}
          id={listId}
          role="listbox"
          style={{ position: 'fixed', top: pos?.top ?? -9999, left: pos?.left ?? -9999, width, maxWidth: 'calc(100vw - 16px)' }}
          className="z-[70] max-h-72 overflow-x-hidden overflow-y-auto rounded-lg border border-border-default bg-bg-surface py-1 text-body shadow-lg"
        >
          {shown.map((o, i) => (
            <li
              key={o}
              id={`${listId}-${i}`}
              data-i={i}
              role="option"
              aria-selected={o === value}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(o)}
              className={cn('flex min-h-8 cursor-pointer items-center gap-2 px-2.5 py-1.5 font-mono text-mono', i === active && 'bg-bg-subtle', o === value ? 'text-accent-text' : 'text-text-primary')}
            >
              <span className="min-w-0 flex-1 break-all">{o}</span>
              {o === value && <Check size={14} aria-hidden className="shrink-0" />}
            </li>
          ))}
        </ul>,
        host,
      )}
    </div>
  )
}
