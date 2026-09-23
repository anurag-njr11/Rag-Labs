import { useState } from 'react'
import { ArrowLeft, ArrowRight, RotateCcw, Zap, ChevronDown } from 'lucide-react'
import { ApiError, errorMessage, useCreateVersion, useRecommendedPipeline, useSmartRecommend } from '@/api/hooks'
import type { PipelineConfig, PipelineFieldError, Project } from '@/api/types'
import { Banner, Button, Spinner, Switch } from '@/components/ui'
import { ConfigEditor } from '@/features/configure'
import { StepIntro, WizardBody, WizardFooter } from './WizardShell'

/**
 * Step 3 — edit the pipeline with the shared ConfigEditor, then save it as the active version
 * (`POST /versions` with `build: false`; the Build step triggers the build).
 */
export function ConfigureStep({
  project, onBack, onNext,
}: { project: Project; onBack: () => void; onNext: (versionId: string) => void }) {
  const recommended = useRecommendedPipeline()
  const smartRec = useSmartRecommend(project.id)
  const initial = project.active_version?.config ?? recommended.data
  const [config, setConfig] = useState<PipelineConfig | undefined>(initial)
  const [errors, setErrors] = useState<PipelineFieldError[]>([])
  const [autoMode, setAutoMode] = useState(true)
  const [showReasoning, setShowReasoning] = useState(false)
  const save = useCreateVersion(project.id)
  // The active config may arrive after first render (recommended fallback).
  const value = config ?? initial

  const applySmartRecommend = () => {
    if (smartRec.data?.config) {
      setConfig(smartRec.data.config)
    }
  }

  // Auto-apply recommendation when entering auto mode
  if (autoMode && smartRec.data?.config && !config) {
    setConfig(smartRec.data.config)
  }

  const submit = () => {
    if (!value) return
    setErrors([])
    save.mutate(
      { config: value, note: 'Initial configuration', activate: true, build: false },
      {
        onSuccess: (r) => onNext(r.version.id),
        onError: (e) => {
          if (e instanceof ApiError && e.fieldErrors.length) setErrors(e.fieldErrors)
        },
      },
    )
  }

  return (
    <div className="flex flex-1 flex-col">
      <WizardBody wide>
        <StepIntro
          title="Configure the pipeline"
          description="Start from the recommended settings or tune each stage. Rebuild settings apply when the index is built; instant settings apply at query time."
        />

        {/* Auto-Configure Toggle */}
        <div className="mb-6 flex items-center justify-between rounded-lg bg-bg-secondary p-4">
          <div className="flex items-center gap-3">
            <Zap size={18} className="text-blue-500" />
            <div>
              <div className="font-medium">Auto-Configure</div>
              <div className="text-sm text-text-secondary">Let the system choose optimal settings based on your documents</div>
            </div>
          </div>
          <Switch checked={autoMode} onChange={setAutoMode} />
        </div>

        {/* Smart Recommendation Summary (when auto mode is on) */}
        {autoMode && smartRec.data && (
          <div className="mb-6 rounded-lg border border-border-primary bg-bg-secondary p-4">
            <div className="mb-4">
              <div className="flex items-center gap-2 font-medium text-text-primary">
                <Zap size={16} className="text-blue-500" />
                Smart Configuration
              </div>
              <div className="mt-1 text-sm text-text-secondary">
                {smartRec.data.metadata.corpus_size > 0
                  ? `Based on ${smartRec.data.metadata.estimated_chunks.toLocaleString()} chunks from ${(smartRec.data.metadata.corpus_size / 1_000_000).toFixed(1)}MB of documents`
                  : 'Default configuration recommended'
                }
              </div>
            </div>

            {/* Recommendation summary grid */}
            <div className="mb-4 grid gap-2">
              {Object.entries(smartRec.data.reasoning).slice(0, 8).map(([stage], idx) => (
                <div key={stage} className="flex items-center gap-2 text-sm">
                  <div className="text-text-secondary">✓</div>
                  <div className="font-mono text-xs uppercase tracking-wider text-text-tertiary min-w-24">{stage}</div>
                  <div className="text-text-primary truncate">{smartRec.data.reasoning[stage]}</div>
                </div>
              ))}
            </div>

            {/* Show Reasoning expandable */}
            <button
              onClick={() => setShowReasoning(!showReasoning)}
              className="flex items-center gap-2 text-sm text-blue-500 hover:text-blue-600 transition-colors"
            >
              <ChevronDown size={14} style={{ transform: showReasoning ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 200ms' }} />
              {showReasoning ? 'Hide reasoning' : 'Show detailed reasoning'}
            </button>

            {/* Expanded reasoning */}
            {showReasoning && (
              <div className="mt-4 space-y-3 border-t border-border-primary pt-4">
                {Object.entries(smartRec.data.reasoning).map(([stage, reason]) => (
                  <div key={stage}>
                    <div className="font-mono text-xs uppercase tracking-wider text-text-tertiary mb-1">{stage}</div>
                    <div className="text-sm text-text-primary">{reason}</div>
                  </div>
                ))}
                {smartRec.data.metadata.confidence < 0.9 && (
                  <div className="mt-3 text-xs text-text-secondary italic border-t border-border-primary pt-3">
                    Confidence: {(smartRec.data.metadata.confidence * 100).toFixed(0)}% (corpus fingerprint: {smartRec.data.metadata.domains.length > 0 ? smartRec.data.metadata.domains.join(', ') : 'general'})
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {save.isError && (
          <Banner tone="danger" title={errors.length ? 'Fix these settings:' : 'Could not save the configuration.'}>
            {errors.length ? (
              <ul className="mt-1 list-disc pl-4">
                {errors.map((er, i) => (
                  <li key={i}>
                    <span className="font-mono text-mono">{er.slot}{er.field ? `.${er.field}` : ''}</span> — {er.message}
                  </li>
                ))}
              </ul>
            ) : (
              errorMessage(save.error)
            )}
          </Banner>
        )}

        {/* Config Editor - hidden in auto mode */}
        {!autoMode && (
          <>
            {value ? (
              <ConfigEditor value={value} onChange={setConfig} projectId={project.id} errors={errors} />
            ) : recommended.isError ? (
              <Banner tone="danger" title="Could not load the recommended pipeline.">{errorMessage(recommended.error)}</Banner>
            ) : (
              <div className="flex justify-center py-12 text-text-tertiary"><Spinner size={20} /></div>
            )}
          </>
        )}
      </WizardBody>
      <WizardFooter step={2} wide>
        <Button icon={<ArrowLeft size={14} aria-hidden />} onClick={onBack}>Back</Button>
        <Button
          icon={<RotateCcw size={14} aria-hidden />}
          disabled={!recommended.data || save.isPending}
          onClick={() => {
            setErrors([])
            setConfig(recommended.data)
          }}
          className="hidden sm:inline-flex"
        >
          Reset to recommended
        </Button>
        <Button variant="primary" loading={save.isPending} disabled={!value} iconRight={<ArrowRight size={14} aria-hidden />} onClick={submit}>
          Save &amp; continue
        </Button>
      </WizardFooter>
    </div>
  )
}
