import { useState } from 'react'
import { FlaskConical, RefreshCw, Sparkles } from 'lucide-react'
import { errorMessage, useEvalSet, useEvalSets, useGenerateEvalSet } from '@/api/hooks'
import { useWorkspace } from '@/app/workspace'
import { Banner, Button, Card, EmptyState, Select, Spinner, useToast } from '@/components/ui'
import { EvalJobProgress } from './EvalJobProgress'
import { EvalSetCard } from './EvalSetCard'
import { RunsPanel } from './RunsPanel'

const SIZES = [10, 20, 30, 50].map((n) => ({ value: String(n), label: `${n} questions` }))

export default function EvaluateTab() {
  const { project } = useWorkspace()
  const sets = useEvalSets(project.id)
  const generate = useGenerateEvalSet(project.id)
  const { toast } = useToast()
  const [size, setSize] = useState('30')
  const [jobId, setJobId] = useState<string | null>(null)

  const latest = sets.data?.[0]
  const current = sets.data?.find((s) => s.status === 'ready') ?? null
  const detail = useEvalSet(project.id, current?.id)
  const generating = !!jobId || latest?.status === 'running'

  const start = () =>
    generate.mutate(
      { size: Number(size) },
      {
        onSuccess: (r) => setJobId(r.job_id),
        onError: (e) => toast({ tone: 'danger', title: 'Could not generate an eval set', description: errorMessage(e) }),
      },
    )

  const controls = (
    <>
      <Select size="md" aria-label="Eval set size" options={SIZES} value={size} onChange={(e) => setSize(e.target.value)} />
      <Button
        variant={current ? 'secondary' : 'primary'}
        icon={current ? <RefreshCw size={14} aria-hidden /> : <Sparkles size={14} aria-hidden />}
        onClick={start}
        loading={generate.isPending}
        disabled={generating || project.documents === 0}
        title={project.documents === 0 ? 'Add documents first' : undefined}
      >
        {current ? 'Regenerate' : 'Generate eval set'}
      </Button>
    </>
  )

  const progress = jobId && (
    <EvalJobProgress
      jobId={jobId}
      projectId={project.id}
      onEnd={() => {
        setJobId(null)
        void sets.refetch()
      }}
    />
  )

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-8 sm:px-8">
      <header className="max-w-3xl">
        <h1 className="text-display text-text-primary">Evaluate</h1>
        <p className="mt-1 text-body-lg text-text-secondary">
          Measure how often retrieval finds the right passage, using questions written from your own documents.
        </p>
      </header>
      {sets.isPending ? (
        <Spinner label="Loading eval sets" />
      ) : sets.isError ? (
        <Banner tone="danger">{errorMessage(sets.error)}</Banner>
      ) : !current ? (
        <Card padding="lg">
          <EmptyState
            icon={<FlaskConical aria-hidden />}
            title="Is this pipeline any good? Measure it."
            description="We write test questions from your own documents, drop the ones a model could answer without them, and score how often retrieval finds the right passage. No labelling."
            actions={
              <div className="flex flex-col items-center gap-3">
                <div className="flex items-center gap-2">{controls}</div>
                {progress}
                {!jobId && latest?.status === 'failed' && (
                  <p role="alert" className="text-body-sm text-danger-fg">Last attempt failed: {latest.error}</p>
                )}
              </div>
            }
          />
        </Card>
      ) : detail.data ? (
        <RunsPanel
          projectId={project.id}
          setId={detail.data.id}
          items={detail.data.items}
          side={
            <EvalSetCard
              compact
              set={detail.data}
              actions={controls}
              progress={
                (jobId || latest?.status === 'failed') && (
                  <>
                    {progress}
                    {!jobId && latest?.status === 'failed' && (
                      <p role="alert" className="text-body-sm text-danger-fg">Regenerating failed: {latest.error}</p>
                    )}
                  </>
                )
              }
            />
          }
        />
      ) : (
        <Spinner label="Loading eval set" />
      )}
    </div>
  )
}
