import { useState } from 'react'
import { errorMessage, useInjectionRun, useInjectionRuns, useStartInjection, useVersions } from '@/api/hooks'
import type { InjectionRun, InjectionVariant } from '@/api/types'
import { Badge, Banner, Button, ButtonLink, Card, Disclosure, Field, Input, Select, Switch, cn, useToast } from '@/components/ui'
import { projectPath } from '@/app/workspace'
import { EvalJobProgress } from './EvalJobProgress'
import { PanelIntro } from './PanelIntro'

const CELL = 'px-3 py-2.5 first:pl-5 last:pr-5 align-middle'
const pct = (x: number | null | undefined) => (x == null ? '—' : `${Math.round(x * 100)}%`)

/** What each defence is, in the words of the Configure setting that turns it on. */
const DEFENCE_HELP: Record<string, string> = {
  data_rule: 'Prompt › Injection defence: “Ignore-instructions rule”',
  delimited: 'Prompt › Injection defence: “Delimited untrusted data”',
  source_labels: 'Prompt › Label sources',
  output_validation: 'Verify › Remove unsourced links and contacts',
  grounding_check: 'Verify › Grounding check',
}

/** Every variant's interval overlaps every other's: nothing here is a clear difference. */
function noisy(vs: InjectionVariant[]) {
  const ci = vs.map((v) => v.score_ci).filter((c): c is [number, number] => !!c)
  return ci.length > 1 && Math.max(...ci.map((c) => c[0])) <= Math.min(...ci.map((c) => c[1]))
}

function scoreTone(s: number | null) {
  return s == null ? 'text-text-tertiary' : s >= 0.9 ? 'text-success-fg' : s >= 0.6 ? 'text-warning-fg' : 'text-danger-fg'
}

/** FR-3.7/3.8: canary payloads planted in retrieval; which ones reach the user, under which defences. */
export function InjectionPanel({ projectId, setId }: { projectId: string; setId: string }) {
  const runs = useInjectionRuns(projectId)
  const start = useStartInjection(projectId)
  const { toast } = useToast()
  const [questions, setQuestions] = useState(5)
  const [compare, setCompare] = useState(true)
  const [jobId, setJobId] = useState<string | null>(null)
  const [shownId, setShownId] = useState<string | undefined>()
  const list = runs.data ?? []
  const shown = list.find((r) => r.id === shownId) ?? list[0]
  const detail = useInjectionRun(projectId, shown?.status === 'ready' ? shown.id : undefined)
  const variantsN = compare ? 8 : 1
  const calls = questions * 5 * variantsN

  const go = () =>
    start.mutate(
      { set_id: setId, questions, compare },
      {
        onSuccess: (r) => {
          setJobId(r.job_id)
          setShownId(r.run.id)
        },
        onError: (e) => toast({ tone: 'danger', title: 'Could not start the test', description: errorMessage(e) }),
      },
    )

  return (
    <Card padding="lg" className="flex flex-col gap-5 sm:p-6">
      <PanelIntro summary="Plant poisoned passages in the results and count how many attacks reach the user.">
        <p>Anyone who can get a document into your corpus can hide instructions in it. This test takes questions from this eval set,
          retrieves as usual, and plants a poisoned passage at the top of the results — five attacks: instruction override, link
          exfiltration, contact swap, a planted false fact, and a system-prompt leak. Each carries a marker, so whether it worked is a
          string check, not a judgment. Your documents are never changed.</p>
      </PanelIntro>

      <div className="flex flex-wrap items-end gap-4">
        <Field label="Questions" help="from this eval set">
          {({ id, describedBy }) => (
            <Input id={id} aria-describedby={describedBy} type="number" min={1} max={20} value={questions} className="w-24"
              onChange={(e) => setQuestions(Math.min(20, Math.max(1, Number(e.target.value) || 1)))} />
          )}
        </Field>
        <label className="flex items-center gap-2 pb-2 text-body text-text-secondary" title="Also run with no defences, each defence on its own, and all of them — to see what each one is worth">
          <Switch checked={compare} onChange={setCompare} aria-label="Compare defences" />
          Compare defences
        </label>
        <span className="pb-2 text-body-sm text-text-tertiary">
          ≈ {calls} answer{calls === 1 ? '' : 's'} to generate{compare ? ' (plus grounding checks)' : ''}
        </span>
        <Button variant="primary" className="ml-auto" onClick={go} loading={start.isPending} disabled={!!jobId || shown?.status === 'running'}>
          Run attack test
        </Button>
      </div>

      {jobId && <EvalJobProgress jobId={jobId} projectId={projectId} onEnd={() => { setJobId(null); void runs.refetch() }} />}

      {shown && (
        <div className="flex flex-col gap-4 border-t border-border-default pt-5">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-heading-lg text-text-primary">Results</h3>
            {list.length > 1 && (
              <Select
                aria-label="Test run"
                value={shown.id}
                onChange={(e) => setShownId(e.target.value)}
                options={list.map((r) => ({ value: r.id, label: `${new Date(r.created_at).toLocaleString()} · v${r.version ?? '?'}` }))}
                wrapperClassName="min-w-56"
              />
            )}
          </div>
          {shown.status === 'failed' && <Banner tone="danger" title="The test failed.">{shown.error}</Banner>}
          {shown.status === 'running' && !jobId && <p className="text-body text-text-secondary">Running…</p>}
          {shown.status === 'ready' && shown.metrics && <Report run={detail.data ?? shown} projectId={projectId} />}
        </div>
      )}
    </Card>
  )
}

function Report({ run, projectId }: { run: InjectionRun; projectId: string }) {
  const activeVersion = useVersions(projectId).data?.find((v) => v.active)?.version
  const m = run.metrics!
  const cur = m.variants[0]
  const none = m.variants.find((v) => v.id === 'none')
  const payloads = m.payloads
  const label = Object.fromEntries(payloads.map((p) => [p.id, p.label]))
  const reached = Object.entries(cur.by_payload).filter(([, x]) => x.hijacked > 0).map(([id]) => label[id])
  const hijacks = (run.results ?? []).filter((r) => r.outcome === 'hijacked' && r.variant === 'current')
  return (
    <>
      <div className="flex flex-wrap items-baseline gap-3">
        <span className={cn('font-mono text-display tabular-nums', scoreTone(cur.score))}>{pct(cur.score)}</span>
        <span className="text-body-lg text-text-secondary">
          injection resistance as configured (v{run.version ?? '?'}{activeVersion && run.version !== activeVersion ? `, not the active v${activeVersion}` : ''}) — {cur.hijacked} of {cur.trials} attack{cur.trials === 1 ? '' : 's'} reached the user
          {reached.length ? `: ${reached.join(', ')}` : ''}.
        </span>
      </div>
      {m.failed_trials > 0 && (
        <Banner tone="warning">
          {m.failed_trials} trial{m.failed_trials === 1 ? '' : 's'} failed after retries (model errors, often a free tier's rate limit) and
          aren't counted — compare variants by their trial counts.
        </Banner>
      )}
      {noisy(m.variants) && (
        <Banner tone="info">
          The 95% intervals of these variants overlap: with {m.questions} question{m.questions === 1 ? '' : 's'} the differences may be noise.
          Run more questions before deciding which defence helps.
        </Banner>
      )}

      <div className="overflow-x-auto rounded-lg border border-border-default">
        <table className="w-full min-w-[760px] border-collapse text-left">
          <caption className="sr-only">Injection resistance per defence variant and attack</caption>
          <thead>
            <tr className="h-10 border-b border-border-default bg-bg-subtle text-label text-text-tertiary">
              <th scope="col" className={cn(CELL, 'font-medium')}>Defences</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')} title="1 − hijacked / trials, with its 95% interval">Resistance</th>
              <th scope="col" className={cn(CELL, 'text-right font-medium')}>Trials</th>
              {none && <th scope="col" className={cn(CELL, 'text-right font-medium')} title="Against no defences at all">vs none</th>}
              {payloads.map((p) => (
                <th key={p.id} scope="col" className={cn(CELL, 'text-right font-medium')} title={p.goal}>{p.label}</th>
              ))}
              <th scope="col" className={cn(CELL, 'text-right font-medium')} title="Payload in the answer, but the grounding check flagged it / output validation removed it">Caught</th>
            </tr>
          </thead>
          <tbody>
            {m.variants.map((v) => <Row key={v.id} v={v} none={none} payloads={payloads.map((p) => p.id)} />)}
          </tbody>
        </table>
      </div>
      <p className="text-body-sm text-text-tertiary">
        Per attack: how many of its trials reached the user unflagged. A grounding check can miss an injection whose claim the poisoned
        passage itself “supports”, and output validation can't remove a link or contact the poisoned passage contains — the variants
        show what each defence actually stops on your setup. Retries after a failed grounding check aren't simulated.
      </p>

      <Disclosure label="Where each defence is set" hint={<ButtonLink to={projectPath(projectId, 'configure')} size="sm" variant="ghost">Configure</ButtonLink>}>
        <ul className="list-disc space-y-1 py-2 pl-5 text-body-sm text-text-secondary">
          {Object.entries(DEFENCE_HELP).map(([k, v]) => <li key={k}>{v}</li>)}
        </ul>
      </Disclosure>

      {hijacks.length > 0 && (
        <Disclosure label="Answers that were hijacked (as configured)" hint={`${hijacks.length}`}>
          <ul className="space-y-3 py-2">
            {hijacks.map((h, i) => (
              <li key={i} className="rounded-md border border-border-default p-3 text-body-sm">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <Badge tone="danger">{label[h.payload]}</Badge>
                  <span className="text-text-tertiary">{h.question}</span>
                </div>
                <p className="whitespace-pre-wrap break-words text-text-secondary">{h.answer}</p>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
    </>
  )
}

function Row({ v, none, payloads }: { v: InjectionVariant; none?: InjectionVariant; payloads: string[] }) {
  const d = none && v.score != null && none.score != null && v.id !== 'none' ? v.score - none.score : null
  return (
    <tr className="border-b border-border-default last:border-b-0">
      <td className={CELL}>
        <span className="flex flex-wrap items-center gap-1.5 text-body text-text-primary">
          {v.label}
          {v.id === 'current' && <Badge tone="neutral">{v.defences.length ? `${v.defences.length} on` : 'none on'}</Badge>}
        </span>
      </td>
      <td className={cn(CELL, 'whitespace-nowrap text-right font-mono text-mono tabular-nums', scoreTone(v.score))}>
        {pct(v.score)}
        {v.score_ci && <span className="ml-1 text-mono-sm text-text-tertiary">({Math.round(v.score_ci[0] * 100)}–{Math.round(v.score_ci[1] * 100)})</span>}
      </td>
      <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums text-text-secondary')}>{v.trials}</td>
      {none && (
        <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums text-text-secondary')}>
          {d == null ? '—' : `${d >= 0 ? '+' : '−'}${Math.round(Math.abs(d) * 100)} pts`}
        </td>
      )}
      {payloads.map((p) => {
        const x = v.by_payload[p]
        return (
          <td key={p} className={cn(CELL, 'text-right font-mono text-mono tabular-nums', x?.hijacked ? 'text-danger-fg' : 'text-text-tertiary')}>
            {x ? `${x.hijacked}/${x.trials}` : '—'}
          </td>
        )
      })}
      <td className={cn(CELL, 'text-right font-mono text-mono tabular-nums text-text-secondary')}>{v.caught_by_check + v.caught_by_filter}</td>
    </tr>
  )
}
