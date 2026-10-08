import { useState } from 'react'
import { WandSparkles } from 'lucide-react'
import { errorMessage, useCreateVersion, usePromptRuns, useStartPromptRun, useVersions } from '@/api/hooks'
import type { PromptRun } from '@/api/types'
import { Badge, Banner, Button, Card, CodeBlock, Disclosure, Select, cn, useToast } from '@/components/ui'
import { EvalJobProgress } from './EvalJobProgress'

const sc = (x: number | null | undefined) => (x == null ? '—' : x.toFixed(2))

/** FR-3.11: search instructions + few-shot examples against the eval set; report on held-out questions. */
export function PromptOptPanel({ projectId, setId }: { projectId: string; setId: string }) {
  const runs = usePromptRuns(projectId)
  const start = useStartPromptRun(projectId)
  const versions = useVersions(projectId)
  const save = useCreateVersion(projectId)
  const { toast } = useToast()
  const [jobId, setJobId] = useState<string | null>(null)
  const [shownId, setShownId] = useState<string | undefined>()
  const list = runs.data ?? []
  const shown = list.find((r) => r.id === shownId) ?? list[0]
  const active = versions.data?.find((v) => v.active)

  const go = () =>
    start.mutate({ set_id: setId }, {
      onSuccess: (r) => { setJobId(r.job_id); setShownId(r.run.id) },
      onError: (e) => toast({ tone: 'danger', title: 'Could not start', description: errorMessage(e) }),
    })

  const use = (run: PromptRun) => {
    if (!active || !run.result) return
    const { extra_instructions, examples } = run.result.best
    const config = { ...active.config, prompt: { ...active.config.prompt, extra_instructions, examples } }
    save.mutate({ config, note: 'Optimised prompt (instructions + examples)', activate: true, build: true }, {
      onSuccess: (r) => toast({
        tone: 'success',
        title: r.unchanged ? 'Already active' : `Saved v${r.version.version} with the optimised prompt`,
        description: r.eval_job_id ? 'Now active — re-scoring it on the eval set.' : 'Now active.',
      }),
      onError: (e) => toast({ tone: 'danger', title: 'Could not save the version', description: errorMessage(e) }),
    })
  }

  return (
    <Card padding="lg" className="flex flex-col gap-5 sm:p-6">
      <div className="max-w-3xl">
        <h2 className="flex items-center gap-2 text-title-lg text-text-primary"><WandSparkles size={20} aria-hidden /> Prompt optimisation</h2>
        <p className="mt-1 text-body-lg text-text-secondary">
          Turns prompt tweaking into a search, the DSPy way. Questions are split train / val / test. The model's best answers to the train
          questions become few-shot examples; it drafts alternative instructions from its weakest ones; every combination answers the val
          questions; the winner and your current prompt then answer the test questions — which played no part in choosing. Score: word overlap
          with the gold answer (F1), halved when citations are missing.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-body-sm text-text-tertiary">
          Optimises the active version{active ? ` (v${active.version})` : ''}. Needs ≥ 9 questions; roughly (2 × candidates + 3) × the set size / 3 answers.
        </span>
        <Button variant="primary" className="ml-auto" onClick={go} loading={start.isPending} disabled={!!jobId || shown?.status === 'running'}>
          Optimise prompt
        </Button>
      </div>
      {jobId && <EvalJobProgress jobId={jobId} projectId={projectId} onEnd={() => { setJobId(null); void runs.refetch() }} />}

      {shown && (
        <div className="flex flex-col gap-4 border-t border-border-default pt-5">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-heading-lg text-text-primary">Result</h3>
            {list.length > 1 && (
              <Select aria-label="Optimisation run" value={shown.id} onChange={(e) => setShownId(e.target.value)} wrapperClassName="min-w-56"
                options={list.map((r) => ({ value: r.id, label: `${new Date(r.created_at).toLocaleString()} · v${r.version ?? '?'}` }))} />
            )}
          </div>
          {shown.status === 'failed' && <Banner tone="danger" title="Optimisation failed.">{shown.error}</Banner>}
          {shown.status === 'running' && !jobId && <p className="text-body text-text-secondary">Running…</p>}
          {shown.status === 'ready' && shown.result && (
            <Result run={shown} onUse={() => use(shown)} saving={save.isPending} canUse={!!active} />
          )}
        </div>
      )}
    </Card>
  )
}

function Result({ run, onUse, saving, canUse }: { run: PromptRun; onUse: () => void; saving: boolean; canUse: boolean }) {
  const r = run.result!
  const d = r.test.after - r.test.before
  const ranked = [...r.candidates].sort((a, b) => b.val_score - a.val_score)
  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-title-lg tabular-nums text-text-primary">{sc(r.test.before)} → {sc(r.test.after)}</span>
        <span className={cn('font-mono text-mono', d > 0 ? 'text-success-fg' : d < 0 ? 'text-danger-fg' : 'text-text-tertiary')}>
          ({d >= 0 ? '+' : '−'}{Math.abs(d).toFixed(2)})
        </span>
        <span className="text-body text-text-secondary">on {r.test.n} unseen test question{r.test.n === 1 ? '' : 's'}</span>
        {r.best.is_current
          ? <Badge tone="neutral">your current prompt won</Badge>
          : r.improves ? <Badge tone="success">improves unseen questions</Badge> : <Badge tone="warning">no gain on unseen questions</Badge>}
        {!r.best.is_current && (
          <Button size="sm" variant={r.improves ? 'primary' : 'secondary'} className="ml-auto" onClick={onUse} loading={saving} disabled={!canUse}>
            Use in a new version
          </Button>
        )}
      </div>
      <p className="text-body-sm text-text-tertiary">
        Split {r.splits.train} / {r.splits.val} / {r.splits.test} · {r.candidates.length} candidates · {r.demos} bootstrapped example{r.demos === 1 ? '' : 's'}.
        Small test sets are noisy; using it saves a version and re-scores it with the judge-graded eval.
      </p>

      {!r.best.is_current && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <p className="text-label text-text-secondary">Additional instructions</p>
            {r.best.extra_instructions ? <CodeBlock code={r.best.extra_instructions} wrap /> : <p className="text-body-sm text-text-tertiary">None</p>}
          </div>
          <div className="flex flex-col gap-1.5">
            <p className="text-label text-text-secondary">Example answers</p>
            {r.best.examples ? <CodeBlock code={r.best.examples} wrap maxHeight={220} /> : <p className="text-body-sm text-text-tertiary">None</p>}
          </div>
        </div>
      )}

      <Disclosure label="All candidates (val score)" hint={`${r.candidates.length}`}>
        <ul className="space-y-2 py-2">
          {ranked.map((c, i) => (
            <li key={i} className="flex flex-wrap items-start gap-2 text-body-sm">
              <span className="w-12 shrink-0 font-mono text-mono tabular-nums text-text-primary">{sc(c.val_score)}</span>
              <span className="min-w-0 flex-1 text-text-secondary">
                {c.extra_instructions || <em className="text-text-tertiary">no extra instructions</em>}
                {c.examples && <Badge tone="info" className="ml-2">+ examples</Badge>}
                {c.is_current && <Badge tone="neutral" className="ml-2">current</Badge>}
              </span>
            </li>
          ))}
        </ul>
      </Disclosure>

      {r.samples.length > 0 && !r.best.is_current && (
        <Disclosure label="Test answers, before and after" hint={`${r.samples.length}`}>
          <ul className="space-y-3 py-2">
            {r.samples.map((s, i) => (
              <li key={i} className="rounded-md border border-border-default p-3 text-body-sm">
                <p className="font-medium text-text-primary">{s.question}</p>
                <p className="text-text-tertiary">Gold: {s.gold}</p>
                <p className="mt-1 text-text-secondary"><span className="font-mono">{sc(s.before_score)}</span> before: {s.before}</p>
                {s.after != null && <p className="text-text-secondary"><span className="font-mono">{sc(s.after_score)}</span> after: {s.after}</p>}
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
    </>
  )
}
