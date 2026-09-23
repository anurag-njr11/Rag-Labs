import type { ComponentProps, ReactNode } from 'react'
import {
  Check, Circle, CircleCheck, CircleX, Code, LoaderCircle, RefreshCw, Target, Type, Waves, Waypoints, Zap,
} from 'lucide-react'
import type { Effect, FoundBy, IndexStatusValue, ParseQuality } from '@/api/types'
import { cn } from './cn'

export type BadgeTone =
  | 'neutral' | 'accent' | 'success' | 'info' | 'warning' | 'danger'
  | 'instant' | 'rebuild' | 'dense' | 'keyword' | 'exact' | 'storeExact' | 'storeApprox'

const tones: Record<BadgeTone, string> = {
  neutral: 'bg-neutral-bg text-neutral-fg border-neutral-border',
  accent: 'bg-accent-subtle text-accent-text border-accent-border',
  success: 'bg-success-bg text-success-fg border-success-border',
  info: 'bg-info-bg text-info-fg border-info-border',
  warning: 'bg-warning-bg text-warning-fg border-warning-border',
  danger: 'bg-danger-bg text-danger-fg border-danger-border',
  instant: 'bg-instant-bg text-instant-fg border-instant-border',
  rebuild: 'bg-rebuild-bg text-rebuild-fg border-rebuild-border',
  dense: 'bg-dense-bg text-dense-fg border-transparent',
  keyword: 'bg-keyword-bg text-keyword-fg border-transparent',
  exact: 'bg-exact-bg text-exact-fg border-transparent',
  storeExact: 'bg-success-bg text-success-fg border-success-border',
  storeApprox: 'bg-neutral-bg text-neutral-fg border-neutral-border',
}

export interface BadgeProps extends Omit<ComponentProps<'span'>, 'children'> {
  tone?: BadgeTone
  /** Leading 6px status dot (status tones). */
  dot?: boolean
  /** Leading icon element (meaning tones), rendered at 12px. */
  icon?: ReactNode
  children?: ReactNode
}

/** 18px pill, radius sm, caption text. */
export function Badge({ tone = 'neutral', dot, icon, className, children, ...rest }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex h-[18px] shrink-0 items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 text-caption [&_svg]:size-3 [&_svg]:shrink-0',
        tones[tone],
        className,
      )}
      {...rest}
    >
      {dot && <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-current" />}
      {icon}
      {children}
    </span>
  )
}

// ---------------------------------------------------------------------------------------- semantic badges

const EFFECT_HELP: Record<Effect, string> = {
  instant: 'Instant — applies at query time, no re-index',
  rebuild: 'Rebuild — requires re-indexing',
}

/** ⚡ Instant / 🔁 Rebuild. `count` renders "Rebuild ×2". `compact` shows icon only (with a11y label). */
export function EffectBadge({ effect, count, compact, className }: { effect: Effect; count?: number; compact?: boolean; className?: string }) {
  const label = effect === 'instant' ? 'Instant' : 'Rebuild'
  return (
    <Badge
      tone={effect}
      icon={effect === 'instant' ? <Zap aria-hidden /> : <RefreshCw aria-hidden />}
      title={EFFECT_HELP[effect]}
      aria-label={compact ? EFFECT_HELP[effect] : undefined}
      className={cn(compact && 'px-1', className)}
    >
      {!compact && label}
      {!compact && count != null && <span className="font-mono">×{count}</span>}
    </Badge>
  )
}

/** Vector-store search exactness: Exact (Target, success) / Approximate (Waves, neutral). */
export function ExactBadge({ exact, className, label }: { exact: boolean; className?: string; label?: string }) {
  return exact ? (
    <Badge tone="storeExact" icon={<Target aria-hidden />} title="Exact — deterministic (Flat / brute force)" className={className}>
      {label ?? 'Exact'}
    </Badge>
  ) : (
    <Badge tone="storeApprox" icon={<Waves aria-hidden />} title="Approximate — HNSW / IVF" className={className}>
      {label ?? 'Approximate'}
    </Badge>
  )
}

const FOUND_BY: Record<FoundBy, { icon: ReactNode; title: string }> = {
  dense: { icon: <Waypoints aria-hidden />, title: 'dense — vector similarity' },
  keyword: { icon: <Type aria-hidden />, title: 'keyword — BM25' },
  exact: { icon: <Code aria-hidden />, title: 'exact — exact error message / code symbol match' },
}

/** Retrieval path badge (dense / keyword / exact). */
export function FoundByBadge({ path, className, children }: { path: FoundBy; className?: string; children?: ReactNode }) {
  return (
    <Badge tone={path} icon={FOUND_BY[path].icon} title={FOUND_BY[path].title} className={className}>
      {children ?? path}
    </Badge>
  )
}

export type StatusValue = IndexStatusValue | 'indexed' | 'uploaded' | 'no_documents' | 'running' | 'done' | 'queued'

const STATUS: Record<StatusValue, { tone: BadgeTone; label: string; icon: ReactNode }> = {
  ready: { tone: 'success', label: 'Ready', icon: <CircleCheck aria-hidden /> },
  indexed: { tone: 'success', label: 'Indexed', icon: <CircleCheck aria-hidden /> },
  done: { tone: 'success', label: 'Done', icon: <CircleCheck aria-hidden /> },
  building: { tone: 'info', label: 'Building', icon: <LoaderCircle aria-hidden className="animate-spin" /> },
  running: { tone: 'info', label: 'Running', icon: <LoaderCircle aria-hidden className="animate-spin" /> },
  pending: { tone: 'neutral', label: 'Pending', icon: <Circle aria-hidden /> },
  queued: { tone: 'neutral', label: 'Queued', icon: <Circle aria-hidden /> },
  uploaded: { tone: 'neutral', label: 'Pending', icon: <Circle aria-hidden /> },
  not_built: { tone: 'neutral', label: 'Not built', icon: <Circle aria-hidden /> },
  no_documents: { tone: 'neutral', label: 'No documents', icon: <Circle aria-hidden /> },
  stale: { tone: 'warning', label: 'Stale', icon: <Circle aria-hidden /> },
  failed: { tone: 'danger', label: 'Failed', icon: <CircleX aria-hidden /> },
}

/**
 * Build / document status. Default renders a dot; `withIcon` uses the row icon (spinning loader for building).
 * Unknown values fall back to neutral with the raw value as label.
 */
export function StatusBadge({ status, label, withIcon, className }: { status: StatusValue | string; label?: string; withIcon?: boolean; className?: string }) {
  const s = STATUS[status as StatusValue] ?? { tone: 'neutral' as const, label: status, icon: <Circle aria-hidden /> }
  return (
    <Badge tone={s.tone} dot={!withIcon} icon={withIcon ? s.icon : undefined} className={className}>
      {label ?? s.label}
    </Badge>
  )
}

const QUALITY: Record<ParseQuality['score'], { tone: BadgeTone; label: string }> = {
  good: { tone: 'success', label: 'Good' },
  fair: { tone: 'warning', label: 'Fair' },
  poor: { tone: 'danger', label: 'Poor' },
}

/** Parse quality Good / Fair / Poor. Spread extra props (e.g. for a HoverCard trigger). */
export function QualityBadge({ score, className, ...rest }: { score: ParseQuality['score'] } & Omit<BadgeProps, 'tone' | 'dot'>) {
  const q = QUALITY[score]
  return (
    <Badge tone={q.tone} dot className={className} {...rest}>
      {q.label}
    </Badge>
  )
}

export type ChunkState = 'in_context' | 'cited' | 'dropped'

/** Inspector chunk state: In context (accent) / Cited (success, check) / Dropped for budget (neutral). */
export function ChunkStateBadge({ state, className }: { state: ChunkState; className?: string }) {
  if (state === 'cited') return <Badge tone="success" icon={<Check aria-hidden />} className={className}>Cited</Badge>
  if (state === 'in_context') return <Badge tone="accent" dot className={className}>In context</Badge>
  return <Badge tone="neutral" dot className={className}>Dropped for budget</Badge>
}

export type ScoreKind = 'dense' | 'keyword' | 'exact' | 'fused' | 'rerank'
const SCORE_TONE: Record<ScoreKind, string> = {
  dense: 'bg-dense-bg text-dense-fg',
  keyword: 'bg-keyword-bg text-keyword-fg',
  exact: 'bg-exact-bg text-exact-fg',
  fused: 'bg-neutral-bg text-neutral-fg',
  rerank: 'bg-accent-subtle text-accent-text',
}
/** Score chip, e.g. `dense 0.82` in mono-sm on the path colour. */
export function ScoreChip({ kind, value, digits, className }: { kind: ScoreKind; value: number; digits?: number; className?: string }) {
  const d = digits ?? (Math.abs(value) < 0.1 ? 3 : Math.abs(value) < 10 ? 2 : 1)
  return (
    <span className={cn('inline-flex h-[18px] items-center gap-1 rounded-sm px-1.5 font-mono text-mono-sm', SCORE_TONE[kind], className)}>
      {kind} <span className="tabular-nums">{value.toFixed(d)}</span>
    </span>
  )
}
