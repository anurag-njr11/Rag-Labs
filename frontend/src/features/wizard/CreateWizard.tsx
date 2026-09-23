import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FolderX } from 'lucide-react'
import { ApiError, errorMessage, useProject } from '@/api/hooks'
import type { Project } from '@/api/types'
import { PageFallback } from '@/app/AppLayout'
import { projectPath } from '@/app/workspace'
import { Button, ButtonLink, EmptyState } from '@/components/ui'
import { BuildStep } from './BuildStep'
import { ConfigureStep } from './ConfigureStep'
import { DocumentsStep } from './DocumentsStep'
import { NameStep } from './NameStep'
import { WizardHeader } from './WizardShell'

/**
 * /new — 4-step create wizard: Name → Documents → Configure → Build.
 * State lives in the URL (`?project=&step=&v=&job=`) so a reload resumes where you were.
 */
export default function CreateWizard() {
  const [params, setParams] = useSearchParams()
  const projectId = params.get('project') ?? undefined
  const versionId = params.get('v')
  const jobId = params.get('job')
  const rawStep = Number(params.get('step') ?? 0)
  const step = projectId ? Math.min(Math.max(Number.isFinite(rawStep) ? rawStep : 0, 0), versionId ? 3 : 2) : 0
  const q = useProject(projectId)

  const go = (next: number, extra: Record<string, string | null> = {}, id = projectId) => {
    const p = new URLSearchParams()
    if (id) p.set('project', id)
    p.set('step', String(next))
    const merged: Record<string, string | null> = { v: versionId, job: jobId, ...extra }
    if (next < 3) {
      merged.job = null
      if (next < 2) merged.v = null
    }
    for (const [k, v] of Object.entries(merged)) if (v) p.set(k, v)
    setParams(p, { replace: next === step })
    window.scrollTo({ top: 0 })
  }

  const project: Project | undefined = q.data
  const exitTo = project ? projectPath(project.id) : '/'
  const onStepClick = (i: number) => i < step && go(i)

  let body: ReactNode
  if (projectId && q.isPending) {
    body = <PageFallback />
  } else if (projectId && (q.isError || !project)) {
    const gone = q.error instanceof ApiError && q.error.status === 404
    body = (
      <div className="mx-auto w-full max-w-[880px] px-4 py-12">
        <EmptyState
          icon={<FolderX aria-hidden />}
          title={gone ? 'This project no longer exists' : 'Could not load the project'}
          description={gone ? 'It may have been deleted. Start a new one.' : errorMessage(q.error)}
          actions={
            <>
              {!gone && <Button onClick={() => void q.refetch()}>Retry</Button>}
              <Button variant="primary" onClick={() => setParams(new URLSearchParams())}>Start over</Button>
              <ButtonLink to="/">All projects</ButtonLink>
            </>
          }
        />
      </div>
    )
  } else if (step === 0 || !project) {
    body = <NameStep project={project} onNext={(p) => go(1, {}, p.id)} />
  } else if (step === 1) {
    body = <DocumentsStep project={project} onBack={() => go(0)} onNext={() => go(2)} />
  } else if (step === 2) {
    body = <ConfigureStep project={project} onBack={() => go(1)} onNext={(vid) => go(3, { v: vid, job: null })} />
  } else {
    body = (
      <BuildStep
        project={project}
        versionId={versionId!}
        jobId={jobId}
        onJob={(id) => go(3, { job: id })}
        onBackToDocs={() => go(1)}
        onBackToConfig={() => go(2)}
      />
    )
  }

  return (
    <div className="flex flex-1 flex-col">
      <WizardHeader step={step} onStepClick={step < 3 ? onStepClick : undefined} exitTo={exitTo} title={project ? project.name : 'New project'} />
      {body}
    </div>
  )
}
