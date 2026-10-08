import { useState } from 'react'
import { errorMessage, useAdapters, useCreateVersion, useDeleteAdapter, useTrainAdapter, useVersions } from '@/api/hooks'
import type { Adapter, RankScores } from '@/api/types'
import { Badge, Banner, Button, Card, cn, useToast } from '@/components/ui'
import { EvalJobProgress } from './EvalJobProgress'
import { PanelIntro } from './PanelIntro'

const pct = (x: number) => `${Math.round(x * 100)}%`
/** Older adapters (before cross-validation) fall back to "improved the holdout". */
const recommended = (a: Adapter) => a.metrics?.recommended ?? a.metrics?.generalises ?? false

function Change({ label, before, after, fmt }: { label: string; before: number; after: number; fmt: (x: number) => string }) {
  const d = after - before
  return (
    <div className="rounded-lg border border-border-default bg-bg-surface px-3 py-2">
      <dt className="text-caption text-text-tertiary">{label}</dt>
      <dd className="mt-0.5 font-mono text-mono tabular-nums text-text-primary">
        {fmt(before)} → {fmt(after)}{' '}
        <span className={cn('text-mono-sm', d > 0.0005 ? 'text-success-fg' : d < -0.0005 ? 'text-danger-fg' : 'text-text-tertiary')}>
          ({d >= 0 ? '+' : '−'}{label.startsWith('MRR') ? Math.abs(d).toFixed(2) : `${Math.round(Math.abs(d) * 100)} pts`})
        </span>
      </dd>
    </div>
  )
}

function Scores({ title, s, hint }: { title: string; s: { before: RankScores; after: RankScores }; hint: string }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-label text-text-secondary">{title} <span className="font-normal text-text-tertiary">· {s.before.n} questions · {hint}</span></p>
      <dl className="grid grid-cols-2 gap-2">
        <Change label="MRR" before={s.before.mrr} after={s.after.mrr} fmt={(x) => x.toFixed(2)} />
        <Change label="Recall@5" before={s.before.recall_at_k} after={s.after.recall_at_k} fmt={pct} />
      </dl>
    </div>
  )
}

/** FR-3.10: a query-side embedding adapter trained on this eval set's labels. */
export function AdapterPanel({ projectId, setId }: { projectId: string; setId: string }) {
  const adapters = useAdapters(projectId)
  const versions = useVersions(projectId)
  const train = useTrainAdapter(projectId)
  const del = useDeleteAdapter(projectId)
  const save = useCreateVersion(projectId)
  const { toast } = useToast()
  const [jobId, setJobId] = useState<string | null>(null)
  const active = versions.data?.find((v) => v.active)
  const inUse = (active?.config.retrieve as { adapter?: string } | undefined)?.adapter
  const list = adapters.data ?? []

  const go = () =>
    train.mutate({ set_id: setId }, {
      onSuccess: (r) => setJobId(r.job_id),
      onError: (e) => toast({ tone: 'danger', title: 'Could not start training', description: errorMessage(e) }),
    })

  const use = (a: Adapter) => {
    if (!active) return
    const config = { ...active.config, retrieve: { ...active.config.retrieve, adapter: a.id } }
    save.mutate({ config, note: 'Embedding adapter (trained on the eval set)', activate: true, build: true }, {
      onSuccess: (r) => toast({
        tone: 'success',
        title: r.unchanged ? 'Already active' : `Saved v${r.version.version} with the adapter`,
        description: r.eval_job_id ? 'Now active — re-scoring it on the eval set with the full pipeline.' : 'Now active.',
      }),
      onError: (e) => toast({ tone: 'danger', title: 'Could not save the version', description: errorMessage(e) }),
    })
  }

  return (
    <Card padding="lg" className="flex flex-col gap-5 sm:p-6">
      <PanelIntro summary="Train a small query-side adapter on this eval set and see whether it ranks unseen questions better.">
        <p>Adapting an embedding model to your domain normally needs labelled (question, passage) pairs. This eval set is exactly that.
          Training fits a small linear map on the question side (documents and index stay as they are, so nothing is rebuilt), on 75% of
          the questions, and scores it on the 25% it never saw. Then it refits on all of them; that's the adapter you can use.</p>
      </PanelIntro>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-body-sm text-text-tertiary">
          Trains for the active version's embedding model{active ? ` (v${active.version})` : ''}. Needs at least 8 questions whose evidence is in the index. A few seconds on CPU.
        </span>
        <Button variant="primary" className="ml-auto" onClick={go} loading={train.isPending} disabled={!!jobId}>Train adapter</Button>
      </div>
      {jobId && <EvalJobProgress jobId={jobId} projectId={projectId} onEnd={() => { setJobId(null); void adapters.refetch() }} />}

      {list.map((a) => (
        <div key={a.id} className={cn('flex flex-col gap-3 border-t border-border-default pt-4', active && a.version != null && a.version !== active.version && 'opacity-60')}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-body text-text-primary">{new Date(a.created_at).toLocaleString()}</span>
            <span className="text-body-sm text-text-tertiary">
              trained for v{a.version ?? '?'}{active && a.version != null && a.version !== active.version ? ` — not the active version (v${active.version})` : ''}
            </span>
            {a.status === 'running' && <Badge tone="info">training…</Badge>}
            {a.status === 'failed' && <Badge tone="danger">failed</Badge>}
            {a.metrics && (recommended(a)
              ? <Badge tone="success">recommended — improves unseen questions</Badge>
              : <Badge tone="warning">not recommended — {a.metrics.cv_passed === false ? 'no better than the plain embedder' : "doesn't improve unseen questions"}</Badge>)}
            {inUse === a.id && <Badge tone="accent">in use (active version)</Badge>}
            <span className="ml-auto flex gap-2">
              {a.status === 'ready' && inUse !== a.id && recommended(a) && (
                <Button size="sm" variant="primary" onClick={() => use(a)} loading={save.isPending} disabled={!active}>
                  Use in a new version
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => del.mutate(a.id)} disabled={a.status === 'running'}
                title={inUse === a.id ? 'Versions that use it will skip it from then on' : undefined}>
                Delete
              </Button>
            </span>
          </div>
          {a.status === 'failed' && <Banner tone="danger">{a.error}</Banner>}
          {a.metrics && (
            <>
              <div className="grid gap-4 md:grid-cols-2">
                <Scores title="Unseen questions" s={a.metrics.holdout} hint="the honest number" />
                <Scores title="All questions" s={a.metrics.full} hint="in-sample, optimistic" />
              </div>
              <p className="text-body-sm text-text-tertiary">
                Dense-only ranking of the {a.metrics.chunks} chunks it was trained on ({a.metrics.dim}-d). Your pipeline also fuses keyword / exact search
                and may rerank, so using it saves a version and re-scores it with the full pipeline.
                {' '}Regularisation λ = {a.metrics.params.lambda} was chosen by cross-validation on the training questions
                {a.metrics.params.lambda >= 10 ? ' — nothing beat the plain embedder there, so the adapter stays close to it.' : '.'}
                {!a.metrics.generalises && ' It doesn’t improve the unseen questions — more (or more varied) eval questions usually help.'}
              </p>
            </>
          )}
        </div>
      ))}
    </Card>
  )
}
