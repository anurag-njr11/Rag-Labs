import {
  useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject,
} from 'react'
import { createPortal } from 'react-dom'
import { cn } from './cn'

export type Placement = 'top' | 'bottom'

/** Computes a fixed position for a floating element anchored to `anchor` (flips + clamps to the viewport). */
function useFloating(open: boolean, anchor: RefObject<HTMLElement | null>, floating: RefObject<HTMLElement | null>, placement: Placement, align: 'center' | 'start' | 'end') {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    if (!open) return
    const update = () => {
      const a = anchor.current, f = floating.current
      if (!a || !f) return
      const r = a.getBoundingClientRect()
      const w = f.offsetWidth, h = f.offsetHeight, gap = 6, m = 8
      let top = placement === 'top' ? r.top - h - gap : r.bottom + gap
      if (placement === 'top' && top < m) top = r.bottom + gap
      if (placement === 'bottom' && top + h > window.innerHeight - m && r.top - h - gap > m) top = r.top - h - gap
      let left = align === 'start' ? r.left : align === 'end' ? r.right - w : r.left + r.width / 2 - w / 2
      left = Math.max(m, Math.min(left, window.innerWidth - w - m))
      setPos({ top, left })
    }
    update()
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [open, anchor, floating, placement, align])
  return pos
}

export interface TooltipProps {
  content: ReactNode
  children: ReactNode
  placement?: Placement
  className?: string
  /** Delay before showing, ms. */
  delay?: number
}

/** Hover/focus tooltip (bg-inverse). Wraps children in an inline-flex span that carries aria-describedby. */
export function Tooltip({ content, children, placement = 'top', className, delay = 250 }: TooltipProps) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const anchor = useRef<HTMLSpanElement>(null)
  const floating = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pos = useFloating(open, anchor, floating, placement, 'center')

  const show = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setOpen(true), delay)
  }
  const hide = () => {
    if (timer.current) clearTimeout(timer.current)
    setOpen(false)
  }
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  if (content == null || content === '') return <>{children}</>
  return (
    <span
      ref={anchor}
      className="inline-flex"
      aria-describedby={open ? id : undefined}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onKeyDown={(e) => e.key === 'Escape' && hide()}
    >
      {children}
      {open &&
        createPortal(
          <div
            ref={floating}
            id={id}
            role="tooltip"
            style={{ position: 'fixed', top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}
            className={cn('pointer-events-none z-[60] max-w-xs rounded-md bg-bg-inverse px-2 py-1 text-body-sm text-text-inverse shadow-md', className)}
          >
            {content}
          </div>,
          document.body,
        )}
    </span>
  )
}

export interface HoverCardProps {
  /** The trigger. Should be focusable (button/link) for keyboard access; otherwise it's wrapped with tabIndex=0. */
  trigger: ReactNode
  children: ReactNode
  placement?: Placement
  align?: 'center' | 'start' | 'end'
  /** Width in px (default 300). */
  width?: number
  className?: string
  /** Accessible label for the wrapper when the trigger isn't focusable itself. */
  'aria-label'?: string
}

/** Rich hover/focus card (bg-surface, shadow-lg, radius lg, p-3). Stays open while the pointer is over it; Esc closes. */
export function HoverCard({ trigger, children, placement = 'bottom', align = 'start', width = 300, className, ...aria }: HoverCardProps) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const anchor = useRef<HTMLSpanElement>(null)
  const floating = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pos = useFloating(open, anchor, floating, placement, align)

  const show = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setOpen(true), 120)
  }
  const hide = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setOpen(false), 150)
  }
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  return (
    <span
      ref={anchor}
      className="inline-flex"
      tabIndex={0}
      role="button"
      aria-label={aria['aria-label']}
      aria-expanded={open}
      aria-controls={open ? id : undefined}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={(e) => {
        if (!floating.current?.contains(e.relatedTarget as Node)) hide()
      }}
      onClick={() => setOpen((o) => !o)}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          setOpen((o) => !o)
        }
      }}
    >
      {trigger}
      {open &&
        createPortal(
          <div
            ref={floating}
            id={id}
            role="dialog"
            onMouseEnter={show}
            onMouseLeave={hide}
            onBlur={(e) => {
              if (!floating.current?.contains(e.relatedTarget as Node) && !anchor.current?.contains(e.relatedTarget as Node)) hide()
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setOpen(false)
                anchor.current?.focus()
              }
            }}
            style={{ position: 'fixed', top: pos?.top ?? -9999, left: pos?.left ?? -9999, width }}
            className={cn('z-[60] max-w-[calc(100vw-16px)] rounded-lg border border-border-default bg-bg-surface p-3 text-body text-text-primary shadow-lg', className)}
          >
            {children}
          </div>,
          document.body,
        )}
    </span>
  )
}

export interface PopoverProps {
  open: boolean
  onClose: () => void
  /** Element the popover is anchored to. */
  anchor: RefObject<HTMLElement | null>
  children: ReactNode
  placement?: Placement
  align?: 'center' | 'start' | 'end'
  width?: number
  className?: string
  'aria-label'?: string
}

/** Controlled click popover (e.g. delete confirmation). Closes on outside click and Escape; focuses first focusable. */
export function Popover({ open, onClose, anchor, children, placement = 'bottom', align = 'end', width = 280, className, ...aria }: PopoverProps) {
  const floating = useRef<HTMLDivElement>(null)
  const pos = useFloating(open, anchor, floating, placement, align)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!floating.current?.contains(t) && !anchor.current?.contains(t)) onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        anchor.current?.focus()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    const f = floating.current?.querySelector<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
    f?.focus()
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose, anchor])

  if (!open) return null
  return createPortal(
    <div
      ref={floating}
      role="dialog"
      aria-label={aria['aria-label']}
      style={{ position: 'fixed', top: pos?.top ?? -9999, left: pos?.left ?? -9999, width }}
      className={cn('z-[60] max-w-[calc(100vw-16px)] rounded-lg border border-border-default bg-bg-surface p-3 text-body shadow-lg', className)}
    >
      {children}
    </div>,
    document.body,
  )
}
