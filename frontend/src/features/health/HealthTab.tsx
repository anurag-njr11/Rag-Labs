import { useState, type ReactNode } from 'react'
import { Copy, Download, FileQuestion, GitCompareArrows, HeartPulse, Stethoscope } from 'lucide-react'
import {
  errorMessage, healthReportUrl, useHealthReport, useHealthReports, useStartHealthReport,
} from '@/api/hooks'
import { formatNumber, stripTags } from '@/api/format'
import type { GapTopic, GapVerdict, HealthExcerpt, HealthResult, PassagePair } from '@/api/types'
import { useWorkspace } from '@/app/workspace'
import {
  Badge, Banner, Button, Card, Disclosure, EmptyState, ProgressBar, Select, Spinner, Textarea, buttonClasses, cn, useToast,
  type BadgeTone,
} from '@/components/ui'
import { EvalJobProgress } from '@/features/evaluate/EvalJobProgress'

const VERDICT: Record<GapVerdict, { label: string; tone: BadgeTone }> = {
  covered: { label: 'Covered', tone: 'success' },
  partial: { label: 'Partial', tone: 'warning' },
  missing: { label: 'Missing', tone: 'danger' },
}
const pct = (x: number) => `${Math.round(x * 100)}%`

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-border-default bg-bg-surface p-4">
      <dt className="text-label text-text-secondary">{label}</dt>
      <dd className="font-mono text-display tabular-nums text-text-primary">{value}</dd>
      {hint && <dd className="text-body-sm text-text-tertiary">{hint}</dd>}
    </div>
  )
}

function Source({ e }: { e: HealthExcerpt }) {
  const where = [e.document, e.page_start ? `p. ${e.page_start}` : '', stripTags(e.heading_path).split(/\s+>\s+/).join(' › ')]
    .filter(Boolean)
    .join(' · ')
  return <span className="block truncate text-body-sm text-text-tertiary" title={where}>{where}</span>
}

function Excerpt({ e }: { e: HealthExcerpt }) {
  return (
    <div className="min-w-0 rounded-lg bg-bg-subtle p-3">
      <Source e={e} />
      <p className="mt-1 line-clamp-5 whitespace-pre-line text-body-sm text-text-secondary">{e.text}</p>
    </div>
  )
}

// ------------------------------------------------------------------------------------------------ sections

function Backlog({ result }: { result: HealthResult }) {
  const { summary, topics } = result.coverage
  return (
    <Card padding="lg" className="flex flex-col gap-4">
      <div>
        <h2 className="flex items-center gap-2 text-title-lg text-text-primary"><FileQuestion size={20} aria-hidden /> Content backlog</h2>
        <p className="mt-1 text-body text-text-secondary">
          Real questions the pipeline can't fully answer from your documents, grouped by topic, biggest first. Usually
          the content is missing; if you know a page covers it, it's a retrieval miss instead — try a sweep on the Evaluate tab.
        </p>
      </div>
      {summary.n === 0 ? (
        <p className="rounded-lg bg-bg-subtle px-4 py-6 text-center text-body text-text-secondary">
          No real questions yet. Ask some in the Playground, or paste questions from your support tickets and run the check again.
        </p>
      ) : topics.length === 0 ? (
        <p className="rounded-lg bg-bg-subtle px-4 py-6 text-center text-body text-text-secondary">
          Every one of the {summary.n} questions is fully answered by the documents.
        </p>
      ) : (
        <ol className="flex flex-col gap-3">
          {topics.map((t, i) => <TopicRow key={i} rank={i + 1} topic={t} />)}
        </ol>
      )}
      {summary.ungraded > 0 && (
        <p className="text-body-sm text-text-tertiary">{summary.ungraded} question(s) couldn't be graded (the model call failed).</p>
      )}
    </Card>
  )
}

function TopicRow({ rank, topic }: { rank: number; topic: GapTopic }) {
  return (
    <li className="rounded-lg border border-border-default p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-mono text-text-tertiary">{rank}.</span>
        <span className="min-w-0 flex-1 text-heading text-text-primary">{topic.topic}</span>
        <span className="text-body-sm text-text-secondary">
          {topic.count} question{topic.count === 1 ? '' : 's'}
          {topic.missing > 0 && <> · <span className="text-danger-fg">{topic.missing} missing</span></>}
          {topic.partial > 0 && <> · <span className="text-warning-fg">{topic.partial} partial</span></>}
        </span>
      </div>
      <Disclosure label="Questions" className="mt-2">
        <ul className="mt-2 flex flex-col gap-2">
          {topic.questions.map((q, i) => (
            <li key={i} className="flex flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2 text-body text-text-primary">
                <Badge tone={VERDICT[q.verdict].tone}>{VERDICT[q.verdict].label}</Badge>
                {q.question}
                <span className="text-caption text-text-tertiary">{q.source === 'pasted' ? 'pasted' : 'asked in chat'}</span>
              </span>
              {q.passages[0] && <span className="pl-1">Closest passage: <Source e={q.passages[0]} /></span>}
            </li>
          ))}
        </ul>
      </Disclosure>
    </li>
  )
}

function Pairs({ title, icon, pairs, empty, contradiction }: {
  title: string; icon: ReactNode; pairs: PassagePair[]; empty: string; contradiction?: boolean
}) {
  return (
    <Card padding="lg" className="flex flex-col gap-4">
      <h2 className="flex items-center gap-2 text-title-lg text-text-primary">{icon} {title} <Badge tone={pairs.length ? (contradiction ? 'danger' : 'warning') : 'neutral'}>{pairs.length}</Badge></h2>
      {pairs.length === 0 ? (
        <p className="text-body text-text-secondary">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-4">
          {pairs.map((p, i) => (
            <li key={i} className="flex flex-col gap-2">
              <p className="text-body text-text-primary">
                {contradiction ? p.explanation : <><strong>{p.a.document}</strong> ≈ <strong>{p.b.document}</strong></>}
                <span className="ml-2 font-mono text-mono-sm text-text-tertiary">similarity {p.similarity.toFixed(2)}</span>
              </p>
              <div className="grid gap-2 md:grid-cols-2">
                <Excerpt e={p.a} />
                <Excerpt e={p.b} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Usage({ result }: { result: HealthResult }) {
  const u = result.usage
  return (
    <Card padding="lg" className="flex flex-col gap-4">
      <div>
        <h2 className="text-title-lg text-text-primary">Unused content</h2>
        <p className="mt-1 text-body text-text-secondary">
          {u.questions === 0
            ? 'Needs real questions to measure.'
            : `${formatNumber(u.chunks_used)} of ${formatNumber(u.chunks)} chunks reached the prompt for the ${u.questions} questions; ${u.unused_documents} document${u.unused_documents === 1 ? '' : 's'} never did.`}
        </p>
        {u.questions > 0 && u.questions < 30 && (
          <p className="mt-1 text-body-sm text-text-tertiary">With fewer than ~30 questions, "unused" mostly means "nobody asked yet".</p>
        )}
      </div>
      {u.questions > 0 && (
        <ul className="flex flex-col gap-2">
          {u.documents.map((d) => (
            <li key={d.document_id} className="grid grid-cols-[minmax(0,1fr)_140px_64px] items-center gap-3">
              <span className="truncate text-body text-text-primary" title={d.document}>{d.document}</span>
              <ProgressBar value={d.used / Math.max(1, d.chunks)} tone={d.used ? 'accent' : 'neutral'} aria-label={`${d.document}: ${d.used} of ${d.chunks} chunks used`} />
              <span className="text-right font-mono text-mono-sm tabular-nums text-text-secondary">{d.used} / {d.chunks}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------------------------------------ tab

export default function HealthTab() {
  const { project } = useWorkspace()
  const reports = useHealthReports(project.id)
  const start = useStartHealthReport(project.id)
  const { toast } = useToast()
  const [pasted, setPasted] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)

  const list = reports.data ?? []
  const latest = list[0]
  const shownId = picked ?? list.find((r) => r.status === 'ready')?.id ?? null
  const detail = useHealthReport(project.id, shownId)
  const result = detail.data?.result ?? null
  const running = !!jobId || latest?.status === 'running'
  const questions = pasted.split('\n').map((q) => q.trim()).filter(Boolean)

  const run = () =>
    start.mutate(
      { questions },
      {
        onSuccess: (r) => {
          setJobId(r.job_id)
          setPicked(null)
        },
        onError: (e) => toast({ tone: 'danger', title: 'Could not start the check', description: errorMessage(e) }),
      },
    )

  const s = result?.coverage.summary
  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-8 sm:px-8">
      <header className="max-w-3xl">
        <h1 className="text-display text-text-primary">Corpus health</h1>
        <p className="mt-1 text-body-lg text-text-secondary">
          Retrieval can't find what isn't written down. See which real questions your documents can't answer, where they
          contradict each other, and what nobody reads.
        </p>
      </header>

      <Card padding="lg" className="flex flex-col gap-4 sm:p-6">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <label className="flex flex-col gap-1.5">
            <span className="text-label text-text-secondary">Real user questions (optional, one per line)</span>
            <Textarea
              rows={5}
              value={pasted}
              onChange={(e) => setPasted(e.target.value)}
              placeholder={'How do I reset my password?\nCan I export invoices to CSV?'}
            />
            <span className="text-body-sm text-text-tertiary">
              Paste questions from support tickets or search logs. Questions asked in the Playground and API are always included (up to 200 in total).
            </span>
          </label>
          <div className="flex flex-col justify-end gap-3">
            <p className="text-body-sm text-text-tertiary">
              Each question is searched with the active version; your Generate model grades whether the top passages answer it
              (about one call per 5 questions). Similar passages from different documents are checked for contradictions.
            </p>
            <Button variant="primary" icon={<Stethoscope size={14} aria-hidden />} onClick={run} loading={start.isPending}
              disabled={running || project.documents === 0} title={project.documents === 0 ? 'Add documents first' : undefined}>
              {list.length ? 'Run the check again' : 'Check corpus health'}
              {questions.length > 0 && ` (+${questions.length})`}
            </Button>
          </div>
        </div>
        {jobId && (
          <EvalJobProgress jobId={jobId} projectId={project.id} onEnd={() => { setJobId(null); void reports.refetch() }} />
        )}
        {!jobId && latest?.status === 'failed' && <p role="alert" className="text-body-sm text-danger-fg">Last check failed: {latest.error}</p>}
      </Card>

      {reports.isPending ? (
        <Spinner label="Loading reports" />
      ) : !shownId ? (
        !running && (
          <EmptyState
            icon={<HeartPulse aria-hidden />}
            title="No health check yet"
            description="Run one to get a ranked content backlog, contradicting passages and unused documents."
          />
        )
      ) : detail.isPending ? (
        <Spinner label="Loading report" />
      ) : detail.isError ? (
        <Banner tone="danger">{errorMessage(detail.error)}</Banner>
      ) : result && s ? (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-body text-text-secondary">
              v{detail.data?.version ?? '?'} · {new Date(detail.data!.created_at).toLocaleString()}
            </span>
            {list.filter((r) => r.status === 'ready').length > 1 && (
              <Select
                aria-label="Show report"
                options={list.filter((r) => r.status === 'ready').map((r) => ({ value: r.id, label: new Date(r.created_at).toLocaleString() }))}
                value={shownId}
                onChange={(e) => setPicked(e.target.value)}
              />
            )}
            <a href={healthReportUrl(project.id, shownId)} download className={cn(buttonClasses({ variant: 'secondary' }), 'ml-auto')}>
              <Download size={14} aria-hidden /> Download report (.md)
            </a>
          </div>
          <dl className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <Stat label="Answered by the docs" value={s.n ? pct(s.covered_rate) : '—'} hint={s.n ? `${s.covered} of ${s.n} real questions` : 'no questions yet'} />
            <Stat label="Gap topics" value={result.coverage.topics.length} hint={s.n ? `${s.missing} missing · ${s.partial} partial` : undefined} />
            <Stat label="Contradictions" value={result.contradictions.length} hint={`of ${result.pairs_checked} similar pairs checked`} />
            <Stat label="Duplicates" value={result.duplicates.length} hint="near-identical passages" />
            <Stat label="Unused documents" value={result.usage.questions ? result.usage.unused_documents : '—'} hint="never reached the prompt" />
          </dl>
          <Backlog result={result} />
          <div className="grid items-start gap-6 xl:grid-cols-2">
            <Pairs title="Contradictions" icon={<GitCompareArrows size={20} aria-hidden />} pairs={result.contradictions} contradiction
              empty={`None found in the ${result.pairs_checked} most similar passage pairs from different documents.`} />
            <Pairs title="Duplicate content" icon={<Copy size={20} aria-hidden />} pairs={result.duplicates}
              empty="No near-identical passages across documents." />
          </div>
          <Usage result={result} />
        </>
      ) : null}
    </div>
  )
}
