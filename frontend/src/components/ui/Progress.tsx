import { Fragment, useLayoutEffect, useRef, type ReactNode } from 'react'
import { Check } from 'lucide-react'
import { cn } from './cn'
import { MOTION, gsap, prefersReducedMotion } from './motion'

export type ProgressTone = 'accent' | 'success' | 'warning' | 'danger' | 'neutral'
const fill: Record<ProgressTone, string> = {
  accent: 'bg-accent-default',
  success: 'bg-success-fg',
  warning: 'bg-warning-fg',
  danger: 'bg-danger-fg',
  neutral: 'bg-text-disabled',
}

export interface ProgressBarProps {
  /** 0–1. Omit / null for an indeterminate bar. */
  value?: number | null
  tone?: ProgressTone
  className?: string
  'aria-label'?: string
}

/** 6px bar, radius full, track bg-muted. */
export function ProgressBar({ value, tone = 'accent', className, ...aria }: ProgressBarProps) {
  const indeterminate = value == null
  const pct = indeterminate ? 0 : Math.max(0, Math.min(1, value)) * 100
  const bar = useRef<HTMLDivElement>(null)
  const seen = useRef(false)

  // Determinate: tween the width. Indeterminate: a GSAP shuttle that sweeps across the track.
  useLayoutEffect(() => {
    const el = bar.current
    if (!el) return
    if (indeterminate) {
      if (prefersReducedMotion()) {
        gsap.set(el, { xPercent: 100 })
        return
      }
      const t = gsap.fromTo(el, { xPercent: -110 }, { xPercent: 310, duration: 1.3, ease: 'power1.inOut', repeat: -1 })
      return () => {
        t.kill()
      }
    }
    if (!seen.current) gsap.set(el, { width: `${pct}%` })
    else gsap.to(el, { width: `${pct}%`, duration: 0.5, ease: MOTION.out, overwrite: 'auto' })
    seen.current = true
  }, [indeterminate, pct])

  return (
    <div
      role="progressbar"
      aria-label={aria['aria-label']}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      className={cn('relative h-1.5 w-full overflow-hidden rounded-full bg-bg-muted', className)}
    >
      {indeterminate ? (
        <div key="ind" ref={bar} className={cn('absolute inset-y-0 left-0 w-1/3 rounded-full', fill[tone])} />
      ) : (
        <div key="det" ref={bar} className={cn('h-full w-0 rounded-full transition-colors', fill[tone])} />
      )}
    </div>
  )
}

export interface StepperStep {
  label: ReactNode
}
export interface StepperProps {
  steps: StepperStep[]
  /** 0-based index of the current step. Earlier steps are Done. */
  current: number
  /** Optional: make done steps clickable. */
  onStepClick?: (index: number) => void
  className?: string
}

/** Horizontal stepper: numbered circles joined by 48×1 connectors (accent when completed). Labels hide on mobile except current. */
export function Stepper({ steps, current, onStepClick, className }: StepperProps) {
  const list = useRef<HTMLOListElement>(null)
  const prev = useRef<number | null>(null)

  // Connectors fill left→right as steps complete; the new current step pops in.
  useLayoutEffect(() => {
    const el = list.current
    if (!el) return
    const fills = Array.from(el.querySelectorAll<HTMLElement>('[data-fill]'))
    const first = prev.current === null
    const forward = prev.current === null || current >= prev.current
    prev.current = current
    if (first) {
      fills.forEach((f, i) => gsap.set(f, { scaleX: i + 1 <= current ? 1 : 0 }))
      return
    }
    const ordered = forward ? fills : [...fills].reverse()
    const tl = gsap.timeline()
    ordered.forEach((f) => {
      const i = fills.indexOf(f)
      const target = i + 1 <= current ? 1 : 0
      if (Number(gsap.getProperty(f, 'scaleX')) !== target) tl.to(f, { scaleX: target, duration: 0.35, ease: MOTION.inOut })
    })
    const dot = el.querySelector<HTMLElement>('[aria-current="step"] [data-dot]')
    if (dot) tl.fromTo(dot, { scale: 0.6 }, { scale: 1, duration: 0.45, ease: MOTION.spring, clearProps: 'transform' }, '-=0.1')
    return () => {
      tl.progress(1).kill()
    }
  }, [current])

  return (
    <ol ref={list} className={cn('flex items-center gap-3', className)} aria-label="Progress">
      {steps.map((s, i) => {
        const state = i < current ? 'done' : i === current ? 'current' : 'upcoming'
        const clickable = !!onStepClick && state === 'done'
        const content = (
          <>
            <span
              data-dot
              className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full font-mono text-mono-sm transition-colors duration-300',
                state === 'done' && 'bg-accent-default text-text-inverse',
                state === 'current' && 'border-[1.5px] border-accent-default bg-accent-subtle text-accent-text',
                state === 'upcoming' && 'border border-border-strong bg-bg-surface text-text-tertiary',
              )}
            >
              {state === 'done' ? <Check size={12} aria-hidden /> : i + 1}
            </span>
            <span
              className={cn(
                'text-label',
                state === 'upcoming' ? 'text-text-tertiary' : 'text-text-primary',
                state !== 'current' && 'hidden sm:inline',
              )}
            >
              {s.label}
            </span>
          </>
        )
        return (
          <Fragment key={i}>
            {i > 0 && (
              <li aria-hidden className="relative h-px w-6 shrink bg-border-strong sm:w-12">
                <span data-fill className="absolute inset-0 origin-left bg-accent-default" />
              </li>
            )}
            <li aria-current={state === 'current' ? 'step' : undefined} className="flex items-center">
              {clickable ? (
                <button type="button" onClick={() => onStepClick!(i)} className="focus-ring flex items-center gap-2 rounded-md">
                  {content}
                </button>
              ) : (
                <span className="flex items-center gap-2">{content}</span>
              )}
              <span className="sr-only">{state === 'done' ? ' (completed)' : state === 'current' ? ' (current)' : ''}</span>
            </li>
          </Fragment>
        )
      })}
    </ol>
  )
}
