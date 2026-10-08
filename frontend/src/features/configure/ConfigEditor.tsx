import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ElementType, type ReactNode } from 'react'
import { ArrowRight, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { errorMessage } from '@/api/client'
import { useCacheStats, useClearCache, useNodes } from '@/api/hooks'
import { formatNumber } from '@/api/format'
import type { Change, NodeConfig, NodeType, PipelineConfig, PipelineFieldError, Slot, SlotCatalog } from '@/api/types'
import { SLOTS } from '@/api/types'
import { TOPBAR_H } from '@/app/AppLayout'
import {
  Badge, Banner, Button, Card, EffectBadge, ExactBadge, OptionCardGroup, Spinner, cn, smoothScrollTo, useIndicator, useSwapTransition,
  useToast,
} from '@/components/ui'
import { useScrollReveal } from '@/components/ui/scrollReveal'
import { useLabs } from '@/app/labs'
import { denseUsed } from './Canvas.utils'
import { SchemaForm } from './SchemaForm'
import { errorsFor, isExact, localChanges } from './schema'

export interface ConfigEditorProps {
  value: PipelineConfig
  onChange: (c: PipelineConfig) => void
  /** Project the config belongs to (optional; the wizard has none yet). */
  projectId?: string
  /** Field errors from `POST /api/pipelines/validate` or a 422 — shown inline. */
  errors?: PipelineFieldError[]
  /** Saved config to compare against: marks edited stages/fields. Optional. */
  baseline?: PipelineConfig
  className?: string
  /** Rendered above the stage cards (e.g. the build-chat bar), so the stage nav starts level with it. */
  top?: ReactNode
}

/** Stage family hue (same tokens as the canvas). */
const FAMILY_OF: Record<string, string> = {
  parse: 'index', chunk: 'index', embed: 'index', vector_store: 'index', retrieve: 'retrieve', rerank: 'retrieve',
  cache: 'gate', compute: 'gate', prompt: 'generate', generate: 'generate', verify: 'generate',
}
const familyColor = (slot: string) => `var(--color-fam-${FAMILY_OF[slot] ?? 'io'})`

const stageId = (slot: Slot) => `stage-${slot}`

/** Short label for the chosen option in the stage nav: the model when one is set, else the type title. */
function chosenLabel(cfg: NodeConfig | undefined, nt: NodeType | undefined) {
  if (!cfg) return '—'
  const model = cfg.model
  if (typeof model === 'string' && model) return model.split('/').pop() ?? model
  return nt?.title ?? cfg.type
}

/**
 * Full pipeline editor: sticky stage nav (desktop) + one card per stage with a type picker and a
 * schema-driven parameter form. Controlled: `value` in, `onChange` out. Never hardcodes node fields.
 */
export function ConfigEditor({ value, onChange, errors, baseline, className, projectId, top }: ConfigEditorProps) {
  const nodes = useNodes()
  const [active, setActive] = useState<Slot>('parse')
  const catalog = nodes.data
  const dense = denseUsed(value)
  const labs = useLabs()
  const computeOn = (value.compute?.type ?? 'none') !== 'none'
  const slots = useMemo(() => SLOTS.filter((s) => s !== 'compute' || labs || computeOn), [labs, computeOn])
  const warns: Partial<Record<Slot, string>> = {
    ...(value.verify?.type === 'none' ? { verify: "Off — answers aren't checked against their sources." } : {}),
    ...((value.prompt as { injection_guard?: string } | undefined)?.injection_guard === 'none'
      ? { prompt: 'No injection defence — instructions hidden in documents can steer answers.' } : {}),
  }
  // Latest value, so two edits in the same tick don't overwrite each other (onChange takes a full config).
  const latest = useRef(value)
  useLayoutEffect(() => {
    latest.current = value
  }, [value])
  const setSlot = (slot: Slot, cfg: NodeConfig) => {
    const next = { ...latest.current, [slot]: cfg }
    latest.current = next
    onChange(next)
  }

  const changes = useMemo(() => localChanges(baseline, value, catalog), [baseline, value, catalog])
  const changedBySlot = useMemo(() => {
    const m = new Map<Slot, Change[]>()
    for (const c of changes) m.set(c.slot, [...(m.get(c.slot) ?? []), c])
    return m
  }, [changes])

  // Stage nav: one GSAP-driven highlight that glides to the active stage. Stage cards reveal on scroll.
  const navList = useRef<HTMLOListElement>(null)
  const navIndicator = useRef<HTMLSpanElement>(null)
  useIndicator(navList, navIndicator, '[aria-current="location"]', [active, !!catalog])
  const stages = useRef<HTMLDivElement>(null)
  useScrollReveal(stages, '[data-stage-card]', [!!catalog])

  // Track the stage in view for the nav highlight.
  useEffect(() => {
    if (!catalog) return
    const els = slots.map((s) => document.getElementById(stageId(s))).filter((e): e is HTMLElement => !!e)
    const visible = new Set<string>()
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.add(e.target.id)
          else visible.delete(e.target.id)
        }
        const first = slots.find((s) => visible.has(stageId(s)))
        if (first) setActive(first)
      },
      { rootMargin: '-120px 0px -55% 0px' },
    )
    els.forEach((e) => obs.observe(e))
    return () => obs.disconnect()
  }, [catalog, slots])

  if (nodes.isLoading) {
    return (
      <div className="flex items-center gap-2 py-10 text-body text-text-secondary">
        <Spinner /> Loading pipeline options…
      </div>
    )
  }
  if (nodes.isError || !catalog) {
    return <Banner tone="danger" title="Couldn't load pipeline options">{errorMessage(nodes.error)}</Banner>
  }

  const jump = (slot: Slot) => {
    setActive(slot)
    const el = document.getElementById(stageId(slot))
    if (el) smoothScrollTo(el, { offset: TOPBAR_H + 16 })
    el?.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true })
  }
  const otherErrors = (errors ?? []).filter((e) => !SLOTS.includes(e.slot as Slot))

  return (
    // Container query: the stage nav shows only when the editor itself is wide (not in the 880px wizard column).
    <div className={cn('@container', className)}>
      <div className="flex gap-10">
        <nav aria-label="Pipeline stages" className="hidden w-64 shrink-0 @min-[900px]:block">
          <ol ref={navList} className="sticky top-[calc(var(--topbar-h)+16px)] flex flex-col gap-1.5">
            <span
              ref={navIndicator}
              aria-hidden
              className="pointer-events-none invisible absolute left-0 top-0 rounded-lg border border-border-default bg-bg-surface shadow-sm"
            >
              <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent-default" />
            </span>
            {slots.map((slot, i) => {
              const sc = catalog.find((s) => s.slot === slot)
              const cfg = value[slot]
              const nt = sc?.types.find((t) => t.type === cfg?.type)
              const ch = changedBySlot.get(slot)
              const hasErr = errors?.some((e) => e.slot === slot)
              const isActive = active === slot
              return (
                <li key={slot}>
                  <button
                    type="button"
                    onClick={() => jump(slot)}
                    aria-current={isActive ? 'location' : undefined}
                    className={cn(
                      'focus-ring relative flex h-14 w-full items-center gap-3 rounded-lg border px-3.5 text-left transition-colors',
                      isActive ? 'border-transparent' : 'border-transparent hover:bg-bg-subtle',
                    )}
                  >
                    <span
                      className={cn(
                        'flex size-6 shrink-0 items-center justify-center rounded-full font-mono text-mono-sm',
                        isActive ? 'bg-accent-default text-text-inverse' : 'bg-bg-muted',
                      )}
                      style={isActive ? undefined : { color: familyColor(slot) }}
                    >
                      {i + 1}
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="text-heading text-text-primary">{sc?.title ?? slot}</span>
                      <span className="truncate text-body text-text-tertiary">{!dense && (slot === 'embed' || slot === 'vector_store') ? 'Unused (keyword-only)' : chosenLabel(cfg, nt)}</span>
                    </span>
                    {hasErr ? (
                      <TriangleAlert size={14} className="shrink-0 text-danger-fg" aria-label="Has errors" />
                    ) : warns[slot] ? (
                      <span className="size-1.5 shrink-0 rounded-full bg-warning-fg" title={warns[slot]}>
                        <span className="sr-only">{warns[slot]}</span>
                      </span>
                    ) : ch?.length ? (
                      <span
                        className={cn('size-1.5 shrink-0 rounded-full', ch.some((c) => c.effect === 'rebuild') ? 'bg-rebuild-fg' : 'bg-instant-fg')}
                        title={`${ch.length} unsaved change${ch.length > 1 ? 's' : ''}`}
                      >
                        <span className="sr-only">{`${ch.length} unsaved change${ch.length > 1 ? 's' : ''}`}</span>
                      </span>
                    ) : null}
                  </button>
                </li>
              )
            })}
          </ol>
        </nav>

        <div ref={stages} className="flex min-w-0 flex-1 flex-col gap-5">
          {/* Compact stage jump row when the editor is narrow */}
          <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 scrollbar-none @min-[900px]:hidden" role="navigation" aria-label="Pipeline stages">
            {slots.map((slot, i) => {
              const sc = catalog.find((s) => s.slot === slot)
              const ch = changedBySlot.get(slot)
              return (
                <button
                  key={slot}
                  type="button"
                  onClick={() => jump(slot)}
                  className="focus-ring flex shrink-0 items-center gap-1.5 rounded-full border border-border-default bg-bg-surface px-2.5 py-1 text-body-sm text-text-secondary"
                >
                  <span className="font-mono text-mono-sm text-text-tertiary">{i + 1}</span>
                  {sc?.title ?? slot}
                  {ch?.length ? (
                    <span aria-hidden className={cn('size-1.5 rounded-full', ch.some((c) => c.effect === 'rebuild') ? 'bg-rebuild-fg' : 'bg-instant-fg')} />
                  ) : null}
                </button>
              )
            })}
          </div>

          {top}

          {otherErrors.length > 0 && (
            <Banner tone="danger" title="Configuration problems">
              <ul className="list-disc pl-4">
                {otherErrors.map((e, i) => (
                  <li key={i}>{e.field ? `${e.field}: ${e.message}` : e.message}</li>
                ))}
              </ul>
            </Banner>
          )}

          {slots.map((slot, i) => {
            const sc = catalog.find((s) => s.slot === slot)
            return (
              <StageCard
                key={slot}
                n={i + 1}
                slot={slot}
                catalog={sc}
                value={value[slot]}
                baseline={baseline?.[slot]}
                changes={changedBySlot.get(slot)}
                errors={errors}
                onChange={(cfg) => setSlot(slot, cfg)}
                projectId={projectId}
                unused={!dense && (slot === 'embed' || slot === 'vector_store')}
                warn={warns[slot]}
              />
            )
          })}
        </div>
      </div>
    </div>
  )
}

export interface StageCardProps {
  n: number
  slot: Slot
  catalog: SlotCatalog | undefined
  value: NodeConfig | undefined
  baseline?: NodeConfig
  changes?: Change[]
  errors?: PipelineFieldError[]
  onChange: (cfg: NodeConfig) => void
  projectId?: string
  /** The retriever never queries this stage's output (keyword-only), though it is still built. */
  unused?: boolean
  /** A one-line caution under the option list (e.g. a safety check is off). */
  warn?: string
  /** Side-panel density (canvas): no card chrome or intro, title-only option cards, one-column fields. */
  compact?: boolean
}

/** How full the semantic cache is, with a way to empty it (e.g. after fixing a wrong answer). */
function CacheStats({ projectId }: { projectId: string }) {
  const stats = useCacheStats(projectId)
  const clear = useClearCache(projectId)
  const { toast } = useToast()
  if (!stats.data) return null
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 text-body-sm text-text-secondary">
      <span>{formatNumber(stats.data.entries)} cached answer{stats.data.entries === 1 ? '' : 's'} · {formatNumber(stats.data.hits)} hit{stats.data.hits === 1 ? '' : 's'} so far</span>
      <Button
        size="sm"
        variant="ghost"
        disabled={!stats.data.entries}
        loading={clear.isPending}
        onClick={() => clear.mutate(undefined, { onSuccess: (r) => toast({ tone: 'success', title: `Cleared ${r.cleared} cached answer${r.cleared === 1 ? '' : 's'}` }) })}
      >
        Clear cache
      </Button>
    </div>
  )
}

export function StageCard({ n, slot, catalog, value, baseline, changes, errors, onChange, projectId, unused, warn, compact }: StageCardProps) {
  const cfg = value ?? { type: '' }
  const nt = catalog?.types.find((t) => t.type === cfg.type)
  const { fieldErrors, general } = errorsFor(errors, slot)
  const changed = useMemo(() => new Set((changes ?? []).map((c) => c.field)), [changes])
  const typeChanged = !!baseline && baseline.type !== cfg.type
  const isStore = catalog?.types.some((t) => t.exact !== null || t.exact_when) ?? false

  // Generate offers only connected providers; the selected one stays visible (disabled) if it was disconnected.
  const types = (catalog?.types ?? []).filter((t) => slot !== 'generate' || t.available || t.type === cfg.type)
  const items = types.map((t) => {
    const exact = isStore ? isExact(t, cfg) : null
    return {
      value: t.type,
      title: t.title,
      description: t.description,
      disabled: !t.available,
      reason: t.unavailable_reason || 'Not available',
      badges:
        exact !== null || (baseline && baseline.type === t.type && typeChanged) ? (
          <>
            {exact !== null && <ExactBadge exact={exact} />}
            {baseline && baseline.type === t.type && typeChanged && <Badge tone="neutral">Current</Badge>}
          </>
        ) : undefined,
    }
  })

  const Wrapper: ElementType = compact ? 'section' : Card
  const titleId = `${stageId(slot)}-title`
  // Switching the stage type swaps in a new parameter form — let it rise in.
  const form = useRef<HTMLDivElement>(null)
  useSwapTransition(form, cfg.type)
  return (
    <Wrapper id={stageId(slot)} aria-labelledby={titleId} role="region"
      {...(compact ? {} : { 'data-stage-card': '', padding: 'lg', className: 'scroll-mt-[calc(var(--topbar-h)+16px)] sm:p-6' })}>
      <div className={cn('flex flex-wrap items-start justify-between gap-3', compact ? 'sr-only' : 'mb-5')}>
        <div className="min-w-0">
          <h2 id={titleId} tabIndex={-1} className="text-title-lg text-text-primary outline-none">
            <span className="text-text-tertiary">{n}</span> · {catalog?.title ?? slot}
          </h2>
          {catalog?.description && <p className="mt-1 text-body-lg text-text-secondary">{catalog.description}</p>}
        </div>
        {catalog && typeChanged && (
          <span className="flex items-center gap-1.5 text-body text-text-tertiary">
            Changing the type <EffectBadge effect={catalog.effect} />
          </span>
        )}
      </div>

      {unused && (
        <Banner tone="info" className="mb-4">
          Not used at query time: the retriever is keyword-only. This stage is still built (and re-built on changes) — it only matters if you switch to dense, hybrid or fused retrieval.
        </Banner>
      )}

      {general.length > 0 && (
        <Banner tone="danger" className="mb-4">
          {general.join(' ')}
        </Banner>
      )}

      {items.length > 0 && (
        <OptionCardGroup
          compact={compact}
          aria-label={`${catalog?.title ?? slot} type`}
          items={items}
          value={cfg.type}
          onChange={(type) => {
            const t = catalog?.types.find((x) => x.type === type)
            if (t && type !== cfg.type) onChange({ ...t.defaults, type })
          }}
        />
      )}

      {warn && <p className="mt-3 flex items-start gap-1.5 text-body text-warning-fg"><TriangleAlert size={14} className="mt-0.5 shrink-0" aria-hidden />{warn}</p>}

      {slot === 'cache' && projectId && cfg.type !== 'none' && <CacheStats projectId={projectId} />}

      {slot === 'generate' && (
        <Link to="/settings/providers" className="focus-ring mt-3 inline-flex items-center gap-1 rounded-sm text-body-sm text-accent-text hover:underline">
          {types.some((t) => t.available) ? 'Connect another provider' : 'Connect a provider'}{compact ? '' : ' (Gemini, NVIDIA, OpenAI, Anthropic, Ollama, your own endpoint…)'}{' '}
          <ArrowRight size={12} aria-hidden />
        </Link>
      )}

      {!nt && cfg.type && (
        <Banner tone="warning" className="mt-4">
          {`Unknown ${catalog?.title.toLowerCase() ?? slot} type "${cfg.type}" — pick one of the options above.`}
        </Banner>
      )}

      {nt && (
        <div ref={form} className={cn('border-t border-border-default', compact ? 'mt-4 pt-4' : 'mt-6 pt-6')}>
          <SchemaForm
            node={nt}
            slot={catalog}
            value={cfg}
            onChange={onChange}
            errors={fieldErrors}
            changed={typeChanged ? undefined : changed}
            idPrefix={`cfg-${slot}`}
            compact={compact}
          />
        </div>
      )}
    </Wrapper>
  )
}
