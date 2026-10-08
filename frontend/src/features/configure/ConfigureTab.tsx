import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Ellipsis, LayoutList, Network, RotateCcw, Save, Undo2, X } from 'lucide-react'
import { ApiError, errorMessage } from '@/api/client'
import {
  useCreateVersion, useEstimate, useNodes, useRecommendedPipeline, useValidatePipeline, useVersions,
} from '@/api/hooks'
import type { Change, EstimateResult, PipelineConfig, PipelineFieldError, Slot } from '@/api/types'
import { JobProgress } from '@/app/JobProgress'
import { useWorkspace } from '@/app/workspace'
import { Banner, Button, EffectBadge, Input, Popover, Spinner, cn, useToast } from '@/components/ui'
import { BuildChat } from './BuildChat'
import { Canvas } from './Canvas'
import { ConfigEditor } from './ConfigEditor'
import { deepEqual, localChanges } from './schema'

function changedBySlot(changes: Change[]) {
  const m = new Map<Slot, Change[]>()
  for (const c of changes) m.set(c.slot, [...(m.get(c.slot) ?? []), c])
  return m
}

/** Configure tab: edit a draft of the active version's pipeline, see what it costs, save as a new version. */
export default function ConfigureTab() {
  const { project } = useWorkspace()
  const active = project.active_version
  const recommended = useRecommendedPipeline()
  const nodes = useNodes()
  const versions = useVersions(project.id)
  const { toast } = useToast()

  const baseline: PipelineConfig | undefined = active?.config ?? recommended.data
  const baseKey = active?.id ?? (recommended.data ? 'recommended' : null)

  // Draft follows the active version: reset whenever it changes (e.g. after saving).
  const [draft, setDraft] = useState<PipelineConfig | null>(baseline ?? null)
  const [draftFor, setDraftFor] = useState<string | null>(baseKey)
  if (baseKey !== draftFor) {
    setDraftFor(baseKey)
    setDraft(baseline ?? null)
  }

  const [note, setNote] = useState('')
  const [params, setParams] = useSearchParams()
  const view: 'form' | 'canvas' = params.get('view') === 'canvas' ? 'canvas' : 'form'
  const setView = (v: 'form' | 'canvas') => setParams(v === 'canvas' ? { view: 'canvas' } : {}, { replace: true })
  const [moreOpen, setMoreOpen] = useState(false)
  const moreRef = useRef<HTMLButtonElement>(null)
  /** Result of the latest validate → estimate round, tagged with the draft it was computed for. */
  const [check, setCheck] = useState<{
    draft: PipelineConfig
    errors: PipelineFieldError[]
    estimate: EstimateResult | null
    error: string | null
  } | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobFinished, setJobFinished] = useState(false)

  const dirty = !!draft && !!baseline && !deepEqual(draft, baseline)
  const current = dirty && check && check.draft === draft ? check : null
  const errors = current?.errors ?? []
  const estimate = current?.estimate ?? null
  const estimateError = current?.error ?? null
  const checking = dirty && !current

  const validate = useValidatePipeline()
  const estimateM = useEstimate(project.id)
  const createVersion = useCreateVersion(project.id)
  const calls = useRef({ validate: validate.mutateAsync, estimate: estimateM.mutateAsync })
  useEffect(() => {
    calls.current = { validate: validate.mutateAsync, estimate: estimateM.mutateAsync }
  })
  const seq = useRef(0)

  // Debounced validate → estimate on every draft change.
  useEffect(() => {
    const my = ++seq.current
    if (!draft || !dirty) return
    const t = setTimeout(async () => {
      const done = (r: { errors?: PipelineFieldError[]; estimate?: EstimateResult; error?: string }) => {
        if (my === seq.current) setCheck({ draft, errors: r.errors ?? [], estimate: r.estimate ?? null, error: r.error ?? null })
      }
      try {
        const v = await calls.current.validate(draft)
        if (my !== seq.current) return
        if (!v.valid) return done({ errors: v.errors })
        done({ estimate: await calls.current.estimate(draft) })
      } catch (e) {
        if (e instanceof ApiError && e.fieldErrors.length) done({ errors: e.fieldErrors })
        else done({ error: errorMessage(e) })
      }
    }, 450)
    return () => clearTimeout(t)
  }, [draft, dirty])

  // Warn before leaving the page with unsaved edits.
  useEffect(() => {
    if (!dirty) return
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [dirty])

  const local = useMemo(() => (draft ? localChanges(baseline, draft, nodes.data) : []), [baseline, draft, nodes.data])
  const changes = estimate?.changes ?? local
  const nRebuild = changes.filter((c) => c.effect === 'rebuild').length
  const nInstant = changes.length - nRebuild
  const nextVersion = Math.max(project.versions, ...(versions.data ?? []).map((v) => v.version)) + 1

  const save = async () => {
    if (!draft) return
    try {
      const res = await createVersion.mutateAsync({ config: draft, note: note.trim() || undefined })
      if (res.unchanged) {
        toast({ title: 'Nothing to save', description: `This configuration is identical to v${res.version.version}.`, tone: 'info' })
        return
      }
      setNote('')
      toast({
        title: `Saved v${res.version.version}`,
        description:
          (res.job_id ? 'Now active — updating the index.' : 'Now active — no re-index needed.') +
          (res.eval_job_id ? ' Scoring it on your eval set (see Evaluate).' : ''),
        tone: 'success',
      })
      if (res.job_id) {
        setJobFinished(false)
        setJobId(res.job_id)
      }
    } catch (e) {
      if (e instanceof ApiError && e.fieldErrors.length) {
        setCheck({ draft, errors: e.fieldErrors, estimate: null, error: null })
        toast({ title: 'Fix the highlighted fields', description: errorMessage(e), tone: 'danger' })
      } else toast({ title: "Couldn't save", description: errorMessage(e), tone: 'danger' })
    }
  }

  if (!draft) {
    return (
      <div className="px-4 py-6 sm:px-8">
        {recommended.isError ? (
          <Banner tone="danger" title="Couldn't load the configuration">{errorMessage(recommended.error)}</Banner>
        ) : (
          <div className="flex items-center gap-2 text-text-secondary">
            <Spinner /> Loading configuration…
          </div>
        )}
      </div>
    )
  }

  const recommendedSame = !!recommended.data && deepEqual(draft, recommended.data)

  return (
    <div className="flex flex-1 flex-col">
      <div className="@container mx-auto w-full max-w-[1440px] flex-1 px-4 pb-12 pt-8 sm:px-8">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-display text-text-primary">Pipeline configuration</h1>
            <p className="mt-1 text-body-lg text-text-secondary">
              {active ? `Draft based on v${active.version} (active).` : 'Draft based on the recommended pipeline.'}{' '}
              Fields marked <EffectBadge effect="rebuild" className="align-middle" /> re-index your documents.
            </p>
          </div>
          <div className="inline-flex h-8 rounded-md border border-border-strong bg-bg-subtle p-0.5" role="group" aria-label="View">
            {([['form', 'Form', LayoutList], ['canvas', 'Canvas', Network]] as const).map(([v, label, Icon]) => (
              <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
                className={cn('focus-ring inline-flex items-center gap-1.5 rounded px-3 text-label',
                  view === v ? 'border border-border-default bg-bg-surface text-text-primary shadow-sm' : 'border border-transparent text-text-secondary hover:text-text-primary')}>
                <Icon size={14} aria-hidden /> {label}
              </button>
            ))}
          </div>
        </div>
        {view === 'form' ? (
          <ConfigEditor value={draft} onChange={setDraft} projectId={project.id} errors={errors} baseline={baseline}
            top={<BuildChat projectId={project.id} draft={draft} onApply={setDraft} />} />
        ) : (
          <>
            <BuildChat projectId={project.id} draft={draft} onApply={setDraft} />
            <Canvas projectId={project.id} value={draft} onChange={setDraft} baseline={baseline} catalog={nodes.data ?? []}
              errors={errors} changedBySlot={changedBySlot(localChanges(baseline, draft, nodes.data))} />
          </>
        )}
      </div>

      <div
        className="sticky bottom-0 z-20 border-t border-border-default bg-bg-surface shadow-[0_-1px_3px_rgb(16_16_19/0.06),0_-4px_12px_rgb(16_16_19/0.06)]"
        role="region"
        aria-label="Save changes"
      >
        {jobId && (
          <div className="flex items-center gap-3 border-b border-border-default px-4 py-2 sm:px-8">
            <JobProgress
              jobId={jobId}
              projectId={project.id}
              variant="compact"
              title="Updating index"
              className="min-w-0 flex-1"
              onDone={() => setJobFinished(true)}
              onFailed={() => setJobFinished(true)}
            />
            {jobFinished && (
              <Button variant="ghost" size="sm" iconOnly icon={<X size={14} aria-hidden />} aria-label="Dismiss build progress" onClick={() => setJobId(null)} />
            )}
          </div>
        )}
        <div className="flex flex-col gap-3 px-4 py-3 sm:px-8 lg:min-h-16 lg:flex-row lg:items-center lg:gap-4">
          <div className="flex min-w-0 flex-1 flex-col gap-0.5" aria-live="polite">
            <div className="flex flex-wrap items-center gap-2">
              {dirty ? (
                <>
                  <span className="text-label text-text-primary">
                    {changes.length} change{changes.length === 1 ? '' : 's'} · {nRebuild} need{nRebuild === 1 ? 's' : ''} rebuild
                  </span>
                  {nRebuild > 0 && <EffectBadge effect="rebuild" count={nRebuild} />}
                  {nInstant > 0 && <EffectBadge effect="instant" count={nInstant} />}
                  {checking && <Spinner size={12} label="Checking" />}
                </>
              ) : (
                <span className="text-label text-text-secondary">No unsaved changes</span>
              )}
            </div>
            {dirty && (
              <p className="truncate text-body-sm text-text-tertiary" title={estimate?.estimate.message}>
                {errors.length > 0 ? (
                  <span className="text-danger-fg">
                    {errors.length} problem{errors.length === 1 ? '' : 's'} to fix before saving.
                  </span>
                ) : estimateError ? (
                  <span className="text-danger-fg">{estimateError}</span>
                ) : estimate ? (
                  estimate.estimate.message
                ) : (
                  'Estimating…'
                )}
              </p>
            )}
          </div>
          <Input
            aria-label="Note for this version"
            placeholder="Note for this version (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && dirty && !errors.length) void save()
            }}
            wrapperClassName="w-full lg:max-w-[320px] lg:flex-1"
            maxLength={500}
          />
          <div className="flex flex-wrap items-center gap-2">
            {dirty && (
              <Button variant="ghost" icon={<Undo2 size={14} aria-hidden />} onClick={() => setDraft(baseline ?? draft)}>
                Discard
              </Button>
            )}
            <Button ref={moreRef} variant="ghost" iconOnly icon={<Ellipsis size={16} aria-hidden />} aria-label="More draft actions"
              aria-haspopup="dialog" aria-expanded={moreOpen} onClick={() => setMoreOpen((o) => !o)} />
            <Popover open={moreOpen} onClose={() => setMoreOpen(false)} anchor={moreRef} width={240} className="p-1" aria-label="Draft actions">
              <button type="button" disabled={!recommended.data || recommendedSame}
                onClick={() => {
                  setMoreOpen(false)
                  if (recommended.data && window.confirm('Replace the draft with the recommended pipeline? Unsaved edits are lost.')) setDraft(recommended.data)
                }}
                className="focus-ring flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-label hover:bg-bg-subtle disabled:opacity-45">
                <RotateCcw size={14} aria-hidden /> Reset to recommended…
              </button>
            </Popover>
            <Button
              variant="primary"
              icon={<Save size={14} aria-hidden />}
              loading={createVersion.isPending}
              disabled={!dirty || errors.length > 0}
              onClick={() => void save()}
            >
              Save as v{nextVersion}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
