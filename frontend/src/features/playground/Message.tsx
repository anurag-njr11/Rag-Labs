import { useEffect, useState } from 'react'
import { DatabaseZap, History, RotateCcw, ShieldAlert, ShieldCheck, ShieldQuestion, Square, TriangleAlert } from 'lucide-react'
import { formatMs, formatNumber, formatPages, stripTags } from '@/api/format'
import type { Verdict, Verification } from '@/api/types'
import { Badge, Banner, Button, ButtonLink, CitationChip, CopyButton, Disclosure, SourceChip, Spinner, cn } from '@/components/ui'
import { projectPath } from '@/app/workspace'
import { Receipt } from '@/features/data/Receipt'
import { ExecutionSummary } from './ExecutionSummary'
import { Markdown } from './markdown'
import { isActive, type Turn } from './session'

export interface MessageProps {
  turn: Turn
  projectId: string
  /** This turn is the one shown in the Inspector. */
  inspected: boolean
  /** Citation n currently selected (only when inspected). */
  activeN: number | null
  maxTokens?: number
  onCite: (turn: Turn, n: number) => void
  onRetry: (turn: Turn) => void
  onStop: () => void
  onInspect: (turn: Turn) => void
}

/** Seconds since `from`, ticking while `on`. */
function useElapsed(from: number, on: boolean) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!on) return
    const t = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(t)
  }, [on])
  return Math.max(0, Math.floor((now - from) / 1000))
}

const lastHeading = (h: string) => {
  const s = stripTags(h).split(/\s+>\s+/).filter(Boolean).pop() ?? ''
  return s.length > 26 ? `${s.slice(0, 25)}…` : s
}

export function Message({ turn, projectId, inspected, activeN, maxTokens, onCite, onRetry, onStop, onInspect }: MessageProps) {
  const active = isActive(turn)
  const elapsed = useElapsed(turn.startedAt, active)
  const byN = new Map(turn.retrieved.filter((c) => c.context_n != null).map((c) => [c.context_n!, c]))
  const final = turn.status === 'done'

  const cite = (n: number, key: string) => {
    const known = final ? turn.citations.some((c) => c.n === n) || byN.has(n) : byN.has(n)
    if (!known) {
      return (
        <span key={key} className="font-mono text-mono-sm text-text-tertiary" title="This number doesn't match a retrieved source">
          [{n}]
        </span>
      )
    }
    const unsupported = final && turn.verification?.citations?.[n] === 'no'
    return (
      <CitationChip
        key={key}
        n={n}
        active={inspected && activeN === n}
        unsupported={unsupported}
        title={unsupported ? `Source ${n} doesn't support this claim (grounding check)` : undefined}
        onClick={() => onCite(turn, n)}
      />
    )
  }

  // Source chips: one per cited chunk, in [n] order.
  const seen = new Set<string>()
  const chips = [...turn.citations]
    .sort((a, b) => a.n - b.n)
    .filter((c) => (seen.has(c.chunk_id) ? false : (seen.add(c.chunk_id), true)))

  const gen = turn.trace.find((s) => s.step === 'generate')
  const firstToken = typeof gen?.payload?.first_token_ms === 'number' ? (gen.payload.first_token_ms as number) : undefined
  const latency = turn.totals?.latency_ms ?? turn.totals?.ms

  let pending: string | null = null
  if (active && !turn.answer) {
    if (turn.indexMessage) pending = `Updating the index first — ${turn.indexMessage}`
    else if (turn.retries) pending = "A claim wasn't supported by its sources — answering again with more context…"
    else if (turn.status === 'waiting') pending = 'Retrieving passages…'
    else pending = `Retrieved ${turn.retrieved.length} passages · waiting for the model…`
  }

  return (
    <article className="space-y-5" aria-label={`Question: ${turn.question}`}>
      {/* User bubble */}
      <div className="flex justify-end">
        <div className="max-w-[min(600px,90%)] whitespace-pre-wrap break-words rounded-2xl rounded-br-md border border-accent-border bg-accent-subtle px-4 py-3 text-body-lg text-text-primary">
          {turn.question}
        </div>
      </div>

      {/* Assistant */}
      <div className={cn('space-y-3 rounded-lg pl-0 transition-colors', inspected && 'relative')}>
        {turn.cache && (
          <p className="flex flex-wrap items-center gap-1.5 text-body-sm text-text-secondary" title={`Cached ${new Date(turn.cache.created_at).toLocaleString()}`}>
            <Badge tone="info" icon={<DatabaseZap aria-hidden />}>From cache</Badge>
            {Math.round(turn.cache.similarity * 100)}% similar to “{turn.cache.question}” — no retrieval or model call.
          </p>
        )}

        {turn.fromHistory && (
          <p className="inline-flex items-center gap-1 text-caption text-text-tertiary">
            <History size={12} aria-hidden /> From run history
          </p>
        )}

        {pending && (
          <p className="flex items-center gap-2 text-body text-text-secondary" role="status">
            <Spinner size={12} /> {pending}
            {elapsed >= 2 && <span className="font-mono text-mono-sm text-text-tertiary">{elapsed}s</span>}
          </p>
        )}

        {turn.answer && (
          <div aria-live="polite" aria-busy={active} aria-atomic="false">
            <Markdown
              text={turn.answer}
              cite={cite}
              trailing={active ? <span aria-hidden className="ml-0.5 inline-block h-[1.05em] w-0.5 translate-y-[3px] animate-caret bg-text-primary" /> : undefined}
            />
          </div>
        )}

        {active && turn.answer && (
          <p className="flex items-center gap-2 text-caption text-text-tertiary">
            <Spinner size={12} /> {turn.verifying ? (turn.verifyingWhat === 'code' ? 'Running the code in the sandbox…' : 'Checking the answer against its sources…') : 'Generating…'}
          </p>
        )}

        {final && turn.verification && <VerificationSummary v={turn.verification} retries={turn.retries ?? 0} />}

        {final && turn.computation && !turn.computation.attested && turn.answer && (
          <Banner tone="warning" title={`“${turn.computation.name}” matched, but its result didn't pass its checks.`}>
            So this answer comes from the documents — numbers in them may be out of date.
          </Banner>
        )}
        {final && turn.computation && <Receipt r={turn.computation} compact={!turn.computation.attested} />}
        {final && turn.execution && <ExecutionSummary e={turn.execution} />}

        {final && turn.truncated && (
          <Banner
            tone="warning"
            title="Answer cut off."
            actions={
              <ButtonLink to={projectPath(projectId, 'configure')} size="sm" variant="ghost">
                Configure
              </ButtonLink>
            }
          >
            The model hit its output limit{maxTokens ? ` (${formatNumber(maxTokens)} tokens)` : ''} before finishing. Raise <span className="font-medium">Generate › Max tokens</span> or ask a narrower question.
          </Banner>
        )}

        {final && !turn.answer.trim() && <p className="text-body text-text-secondary">The model returned an empty answer.</p>}

        {final && !turn.truncated && turn.answer.trim() && chips.length === 0 && !turn.computation && (
          <p className="text-body-sm text-text-tertiary">
            No sources cited — the retrieved passages didn't contain the answer, so the model declined rather than guess.
          </p>
        )}

        {turn.status === 'error' && turn.error && (
          <Banner
            tone="danger"
            title={turn.retrieved.length ? 'Retrieval worked, but the answer failed.' : "Couldn't answer."}
            actions={
              <>
                {turn.error.code === 'no_documents' ? (
                  <ButtonLink to={projectPath(projectId, 'documents')} size="sm" variant="secondary">Add documents</ButtonLink>
                ) : /api[_ ]key|\.env|model|provider/i.test(turn.error.message) ? (
                  <ButtonLink to={projectPath(projectId, 'configure')} size="sm" variant="ghost">Configure</ButtonLink>
                ) : null}
                <Button size="sm" icon={<RotateCcw size={12} aria-hidden />} onClick={() => onRetry(turn)}>Retry</Button>
              </>
            }
          >
            <span className="break-words">{turn.error.message}</span>
            {turn.retrieved.length > 0 && (
              <span className="mt-1 block text-body-sm text-text-secondary">The retrieved passages are still in the Inspector.</span>
            )}
          </Banner>
        )}

        {turn.status === 'stopped' && (
          <p className="flex items-center gap-2 text-body-sm text-text-secondary">
            <TriangleAlert size={14} aria-hidden className="text-warning-fg" /> Stopped{turn.answer ? ' — the answer above is partial.' : '.'}
            <Button size="sm" variant="ghost" icon={<RotateCcw size={12} aria-hidden />} onClick={() => onRetry(turn)}>Retry</Button>
          </p>
        )}

        {chips.length > 0 && (
          <div className="flex flex-wrap gap-1.5" aria-label="Cited sources">
            {chips.map((c) => (
              <SourceChip
                key={c.chunk_id}
                document={`[${c.n}] ${c.document}`}
                meta={formatPages(c.page_start, c.page_end) || lastHeading(c.heading_path) || undefined}
                title={`[${c.n}] ${c.document}${c.heading_path ? ` — ${stripTags(c.heading_path)}` : ''}`}
                aria-label={`Source ${c.n}: ${c.document}`}
                onClick={() => onCite(turn, c.n)}
              />
            ))}
          </div>
        )}

        {/* Actions */}
        {(final || turn.status === 'error' || turn.status === 'stopped' || active) && (
          <div className="flex flex-wrap items-center gap-1">
            {active ? (
              <Button size="sm" variant="ghost" icon={<Square size={12} aria-hidden />} onClick={onStop}>Stop</Button>
            ) : (
              turn.answer && <CopyButton text={turn.answer} label="Copy" />
            )}
            {!inspected && turn.retrieved.length > 0 && (
              <Button size="sm" variant="ghost" onClick={() => onInspect(turn)}>Inspect sources</Button>
            )}
            {final && latency != null && (
              <span className="ml-auto font-mono text-mono-sm text-text-tertiary">
                {formatMs(latency)}
                {firstToken != null && ` · first token ${formatMs(firstToken)}`}
                {turn.totals && turn.totals.tokens_out > 0 && ` · ${formatNumber(turn.totals.tokens_in)} → ${formatNumber(turn.totals.tokens_out)} tok`}
              </span>
            )}
          </div>
        )}
      </div>
    </article>
  )
}

const VERDICT: Record<Verdict, { label: string; tone: 'success' | 'warning' | 'danger' }> = {
  yes: { label: 'supported', tone: 'success' },
  partial: { label: 'partly supported', tone: 'warning' },
  no: { label: 'not supported', tone: 'danger' },
}

/** Grounding check result (Verify slot): one line, expandable to the per-claim verdicts. */
function VerificationSummary({ v, retries }: { v: Verification; retries: number }) {
  const after = retries ? ` after ${retries} ${retries === 1 ? 'retry' : 'retries'} with more context` : ''
  if (v.status === 'error') {
    return (
      <p className="flex items-center gap-1.5 text-body-sm text-text-tertiary">
        <ShieldQuestion size={14} aria-hidden /> Grounding check couldn't run{v.error ? ` — ${v.error}` : '.'}
      </p>
    )
  }
  const bad = v.claims.filter((c) => c.supported === 'no').length
  const label = !v.claims.length
    ? 'Grounded — no factual claims to check'
    : v.grounded
      ? `Grounded — ${v.claims.length - bad} of ${v.claims.length} claims supported${after}`
      : `Not grounded — ${bad} of ${v.claims.length} claims not supported by the sources${after}`
  return (
    <Disclosure
      label={
        <span className={cn('inline-flex items-center gap-1.5', v.grounded ? 'text-success-fg' : 'text-danger-fg')}>
          {v.grounded ? <ShieldCheck size={14} aria-hidden /> : <ShieldAlert size={14} aria-hidden />}
          {label}
        </span>
      }
      hint={v.score != null ? `score ${Math.round(v.score * 100)}%` : undefined}
    >
      <ul className="space-y-2 py-2">
        {v.claims.map((c, i) => (
          <li key={i} className="flex flex-wrap items-start gap-2 text-body-sm">
            <Badge tone={VERDICT[c.supported].tone} dot>{VERDICT[c.supported].label}</Badge>
            <span className="min-w-0 flex-1 text-text-secondary">{c.claim}</span>
            {Object.entries(c.cited).map(([n, verdict]) => (
              <span key={n} className="font-mono text-mono-sm text-text-tertiary" title={`Source ${n}: ${VERDICT[verdict].label}`}>
                [{n}] {verdict === 'yes' ? '✓' : verdict === 'partial' ? '~' : '✗'}
              </span>
            ))}
          </li>
        ))}
      </ul>
    </Disclosure>
  )
}
