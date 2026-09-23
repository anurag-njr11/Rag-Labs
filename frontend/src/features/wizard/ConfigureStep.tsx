import { useState } from 'react'
import { ArrowLeft, ArrowRight, RotateCcw } from 'lucide-react'
import { ApiError, errorMessage, useCreateVersion, useRecommendedPipeline } from '@/api/hooks'
import type { PipelineConfig, PipelineFieldError, Project } from '@/api/types'
import { Banner, Button, Spinner } from '@/components/ui'
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
  const initial = project.active_version?.config ?? recommended.data
  const [config, setConfig] = useState<PipelineConfig | undefined>(initial)
  const [errors, setErrors] = useState<PipelineFieldError[]>([])
  const save = useCreateVersion(project.id)
  // The active config may arrive after first render (recommended fallback).
  const value = config ?? initial

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
        {value ? (
          <ConfigEditor value={value} onChange={setConfig} projectId={project.id} errors={errors} />
        ) : recommended.isError ? (
          <Banner tone="danger" title="Could not load the recommended pipeline.">{errorMessage(recommended.error)}</Banner>
        ) : (
          <div className="flex justify-center py-12 text-text-tertiary"><Spinner size={20} /></div>
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
