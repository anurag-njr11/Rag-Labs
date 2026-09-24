import { Fragment, type ReactNode } from 'react'
import { Check } from 'lucide-react'
import { cn } from './cn'

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
        <div className={cn('absolute inset-y-0 w-1/3 animate-pulse rounded-full', fill[tone])} style={{ left: '33%' }} />
      ) : (
        <div className={cn('h-full rounded-full transition-[width] duration-300', fill[tone])} style={{ width: `${pct}%` }} />
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
  return (
    <ol className={cn('flex items-center gap-3', className)} aria-label="Progress">
      {steps.map((s, i) => {
        const state = i < current ? 'done' : i === current ? 'current' : 'upcoming'
        const clickable = !!onStepClick && state === 'done'
        const content = (
          <>
            <span
              className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full font-mono text-mono-sm',
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
              <li aria-hidden className={cn('h-px w-6 shrink sm:w-12', i <= current ? 'bg-accent-default' : 'bg-border-strong')} />
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
