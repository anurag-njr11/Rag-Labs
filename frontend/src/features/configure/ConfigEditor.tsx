import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { TriangleAlert } from 'lucide-react'
import { errorMessage } from '@/api/client'
import { useNodes } from '@/api/hooks'
import type { Change, NodeConfig, NodeType, PipelineConfig, PipelineFieldError, Slot, SlotCatalog } from '@/api/types'
import { SLOTS } from '@/api/types'
import { Badge, Banner, Card, EffectBadge, ExactBadge, OptionCardGroup, Spinner, cn } from '@/components/ui'
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
}

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
export function ConfigEditor({ value, onChange, errors, baseline, className }: ConfigEditorProps) {
  const nodes = useNodes()
  const [active, setActive] = useState<Slot>('parse')
  const catalog = nodes.data
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

  // Track the stage in view for the nav highlight.
  useEffect(() => {
    if (!catalog) return
    const els = SLOTS.map((s) => document.getElementById(stageId(s))).filter((e): e is HTMLElement => !!e)
    const visible = new Set<string>()
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.add(e.target.id)
          else visible.delete(e.target.id)
        }
        const first = SLOTS.find((s) => visible.has(stageId(s)))
        if (first) setActive(first)
      },
      { rootMargin: '-120px 0px -55% 0px' },
    )
    els.forEach((e) => obs.observe(e))
    return () => obs.disconnect()
  }, [catalog])

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
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    el?.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true })
  }
  const otherErrors = (errors ?? []).filter((e) => !SLOTS.includes(e.slot as Slot))

  return (
    // Container query: the stage nav shows only when the editor itself is wide (not in the 880px wizard column).
    <div className={cn('@container', className)}>
      <div className="flex gap-10">
        <nav aria-label="Pipeline stages" className="hidden w-64 shrink-0 @min-[900px]:block">
          <ol className="sticky top-[calc(var(--topbar-h)+16px)] flex flex-col gap-1.5">
            {SLOTS.map((slot, i) => {
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
                      isActive ? 'border-border-default bg-bg-surface shadow-sm' : 'border-transparent hover:bg-bg-subtle',
                    )}
                  >
                    {isActive && <span aria-hidden className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent-default" />}
                    <span
                      className={cn(
                        'flex size-6 shrink-0 items-center justify-center rounded-full font-mono text-mono-sm',
                        isActive ? 'bg-accent-default text-text-inverse' : 'bg-bg-muted text-text-tertiary',
                      )}
                    >
                      {i + 1}
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="text-heading text-text-primary">{sc?.title ?? slot}</span>
                      <span className="truncate text-body text-text-tertiary">{chosenLabel(cfg, nt)}</span>
                    </span>
                    {hasErr ? (
                      <TriangleAlert size={14} className="shrink-0 text-danger-fg" aria-label="Has errors" />
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

        <div className="flex min-w-0 flex-1 flex-col gap-5">
          {/* Compact stage jump row when the editor is narrow */}
          <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 scrollbar-none @min-[900px]:hidden" role="navigation" aria-label="Pipeline stages">
            {SLOTS.map((slot, i) => {
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

          {otherErrors.length > 0 && (
            <Banner tone="danger" title="Configuration problems">
              <ul className="list-disc pl-4">
                {otherErrors.map((e, i) => (
                  <li key={i}>{e.field ? `${e.field}: ${e.message}` : e.message}</li>
                ))}
              </ul>
            </Banner>
          )}

          {SLOTS.map((slot, i) => {
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
              />
            )
          })}
        </div>
      </div>
    </div>
  )
}

interface StageCardProps {
  n: number
  slot: Slot
  catalog: SlotCatalog | undefined
  value: NodeConfig | undefined
  baseline?: NodeConfig
  changes?: Change[]
  errors?: PipelineFieldError[]
  onChange: (cfg: NodeConfig) => void
}

function StageCard({ n, slot, catalog, value, baseline, changes, errors, onChange }: StageCardProps) {
  const cfg = value ?? { type: '' }
  const nt = catalog?.types.find((t) => t.type === cfg.type)
  const { fieldErrors, general } = errorsFor(errors, slot)
  const changed = useMemo(() => new Set((changes ?? []).map((c) => c.field)), [changes])
  const typeChanged = !!baseline && baseline.type !== cfg.type
  const isStore = catalog?.types.some((t) => t.exact !== null || t.exact_when) ?? false

  const items = (catalog?.types ?? []).map((t) => {
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
            {t.exact_when && (
              <Badge tone="neutral" title={`Exact when ${Object.entries(t.exact_when).map(([k, v]) => `${k} = ${v.join(' / ')}`).join(', ')}`}>
                {`Exact when ${Object.entries(t.exact_when).map(([k, v]) => `${k}: ${v.join('/')}`).join(', ')}`}
              </Badge>
            )}
            {baseline && baseline.type === t.type && typeChanged && <Badge tone="neutral">Current</Badge>}
          </>
        ) : undefined,
    }
  })

  const titleId = `${stageId(slot)}-title`
  return (
    <Card padding="lg" id={stageId(slot)} aria-labelledby={titleId} role="region" className="scroll-mt-[calc(var(--topbar-h)+16px)] sm:p-6">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={titleId} tabIndex={-1} className="text-title-lg text-text-primary outline-none">
            <span className="text-text-tertiary">{n}</span> · {catalog?.title ?? slot}
          </h2>
          {catalog?.description && <p className="mt-1 text-body-lg text-text-secondary">{catalog.description}</p>}
        </div>
        {catalog && (
          <span className="flex items-center gap-1.5 text-body text-text-tertiary">
            Changing the type <EffectBadge effect={catalog.effect} />
          </span>
        )}
      </div>

      {general.length > 0 && (
        <Banner tone="danger" className="mb-4">
          {general.join(' ')}
        </Banner>
      )}

      {items.length > 0 && (
        <OptionCardGroup
          aria-label={`${catalog?.title ?? slot} type`}
          items={items}
          value={cfg.type}
          onChange={(type) => {
            const t = catalog?.types.find((x) => x.type === type)
            if (t && type !== cfg.type) onChange({ ...t.defaults, type })
          }}
        />
      )}

      {!nt && cfg.type && (
        <Banner tone="warning" className="mt-4">
          {`Unknown ${catalog?.title.toLowerCase() ?? slot} type "${cfg.type}" — pick one of the options above.`}
        </Banner>
      )}

      {nt && (
        <div className="mt-6 border-t border-border-default pt-6">
          <SchemaForm
            node={nt}
            slot={catalog}
            value={cfg}
            onChange={onChange}
            errors={fieldErrors}
            changed={typeChanged ? undefined : changed}
            idPrefix={`cfg-${slot}`}
          />
        </div>
      )}
    </Card>
  )
}
