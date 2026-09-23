import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, FileText, MessageCircle, RefreshCw } from 'lucide-react'
import { ApiError, errorMessage, useBuildVersion } from '@/api/hooks'
import { formatNumber, storeLabel } from '@/api/format'
import type { JobDoneResult, Project } from '@/api/types'
import { JobProgress } from '@/app/JobProgress'
import { projectPath } from '@/app/workspace'
import { Banner, Button, ButtonLink, Card, Spinner } from '@/components/ui'
import { StepIntro, WizardBody, WizardFooter } from './WizardShell'

/**
 * Step 4 — trigger `POST /versions/{vid}/build` once, stream it with JobProgress, finish → Playground.
 * The job id is kept in the URL (`job`) so a reload re-attaches instead of starting another build.
 */
export function BuildStep({
  project, versionId, jobId, onJob, onBackToDocs, onBackToConfig,
}: {
  project: Project
  versionId: string
  jobId: string | null
  onJob: (jobId: string | null) => void
  onBackToDocs: () => void
  onBackToConfig: () => void
}) {
  const build = useBuildVersion(project.id)
  const started = useRef<string | null>(null)
  const [result, setResult] = useState<{ ok: true; r: JobDoneResult } | { ok: false; error: string } | null>(null)

  const start = () => {
    setResult(null)
    build.mutate(versionId, { onSuccess: (r) => onJob(r.job_id) })
  }

  useEffect(() => {
    if (jobId || started.current === versionId) return
    started.current = versionId
    start()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per version
  }, [versionId, jobId])

  const noDocs = build.error instanceof ApiError && build.error.status === 409
  const done = result?.ok === true
  const failed = result?.ok === false || build.isError
  const version = project.active_version?.id === versionId ? project.active_version : null

  return (
    <div className="flex flex-1 flex-col">
      <WizardBody>
        <StepIntro
          title={done ? 'Your index is ready' : 'Build the index'}
          description={
            done
              ? 'Ask questions in the Playground — every answer cites its sources.'
              : `Parsing, chunking and embedding ${formatNumber(project.documents)} document${project.documents === 1 ? '' : 's'}${version ? ` with v${version.version}` : ''}. You can leave this page; the build keeps running.`
          }
        />
        {build.isError && (
          <Banner
            tone="danger"
            title={noDocs ? 'No documents to index.' : 'Could not start the build.'}
            actions={
              noDocs ? (
                <Button size="sm" onClick={onBackToDocs}>Add documents</Button>
              ) : (
                <Button size="sm" onClick={start}>Retry</Button>
              )
            }
          >
            {errorMessage(build.error)}
          </Banner>
        )}
        <Card padding="lg">
          {jobId ? (
            <JobProgress
              key={jobId}
              jobId={jobId}
              projectId={project.id}
              title="Building index"
              onDone={(r) => setResult({ ok: true, r })}
              onFailed={(error) => setResult({ ok: false, error })}
            />
          ) : build.isPending || !build.isError ? (
            <div className="flex items-center gap-3 py-6 text-body text-text-secondary">
              <Spinner /> Starting build…
            </div>
          ) : (
            <p className="py-4 text-body text-text-tertiary">The build hasn’t started.</p>
          )}
        </Card>
        {done && result.ok && (
          <Card padding="lg" className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              ['Documents', formatNumber(project.documents)],
              ['Chunks', formatNumber(result.r.build?.chunk_count ?? 0)],
              ['Vector store', storeLabel(project.summary?.vector_store ?? project.index?.store)],
              ['Took', result.r.build?.stats ? `${result.r.build.stats.seconds.toFixed(1)} s` : '—'],
            ].map(([k, v]) => (
              <div key={k}>
                <p className="text-caption text-text-tertiary">{k}</p>
                <p className="mt-0.5 font-mono text-mono text-text-primary">{v}</p>
              </div>
            ))}
          </Card>
        )}
      </WizardBody>
      <WizardFooter
        step={3}
        hint={done ? 'Step 4 of 4 · done' : failed ? 'Step 4 of 4 · build failed — adjust settings or retry' : 'Step 4 of 4 · building…'}
      >
        {failed && (
          <>
            <Button icon={<ArrowLeft size={14} aria-hidden />} onClick={onBackToConfig}>Back to settings</Button>
            {!build.isError && (
              <Button
                icon={<RefreshCw size={14} aria-hidden />}
                onClick={() => {
                  onJob(null)
                  start()
                }}
              >
                Retry build
              </Button>
            )}
          </>
        )}
        {!failed && (
          <ButtonLink to={projectPath(project.id, 'documents')} icon={<FileText size={14} aria-hidden />}>
            View documents
          </ButtonLink>
        )}
        <ButtonLink
          to={projectPath(project.id, 'playground')}
          variant="primary"
          icon={<MessageCircle size={14} aria-hidden />}
          aria-disabled={!done || undefined}
          tabIndex={done ? undefined : -1}
          onClick={(e) => !done && e.preventDefault()}
        >
          Open Playground
        </ButtonLink>
      </WizardFooter>
    </div>
  )
}
