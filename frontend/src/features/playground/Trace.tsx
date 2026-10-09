import { useRun } from '@/api/hooks'
import { formatCost, formatMs, formatNumber, shortHash, storeLabel } from '@/api/format'
import type { TraceStep } from '@/api/types'
import { CodeBlock, CopyButton, Disclosure, ExactBadge, Spinner, cn } from '@/components/ui'
import { isActive, type Turn } from './session'

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)
const str = (v: unknown) => (typeof v === 'string' && v ? v : undefined)

/** Short, human facts from a step payload. */
function payloadFacts(s: TraceStep): string[] {
  const p = s.payload ?? {}
  const f: string[] = []
  if ((s.step as string) === 'pin') {
    if (num(p.pinned) != null) f.push(`${p.pinned} defining section${p.pinned === 1 ? '' : 's'} moved to the top`)
    return f
  }
  switch (s.step) {
    case 'embed_query':
      if (str(p.model)) f.push(String(p.model))
      if (str(p.adapter)) f.push(String(p.adapter).startsWith('skipped') ? `adapter ${p.adapter}` : 'adapter applied')
      break
    case 'dense_search':
      if (num(p.hits) != null) f.push(`${p.hits} hits`)
      if (str(p.store)) f.push(storeLabel(String(p.store)))
      if (typeof p.exact === 'boolean') f.push(p.exact ? 'exact' : 'approximate')
      break
    case 'keyword_search':
    case 'exact_search':
      if (num(p.hits) != null) f.push(`${p.hits} hit${p.hits === 1 ? '' : 's'}`)
      if (p.used === false) f.push('not used — the question only mentions the identifier in passing')
      break
    case 'fuse':
      if (str(p.method)) f.push(String(p.method).toUpperCase())
      if (num(p.candidates) != null) f.push(`${p.candidates} candidates`)
      break
    case 'prompt':
      if (num(p.included) != null) f.push(`${p.included} in context`)
      if (num(p.dropped) != null) f.push(`${p.dropped} dropped`)
      break
    case 'generate':
      if (str(p.model)) f.push(String(p.model))
      if (num(p.first_token_ms) != null) f.push(`first token ${formatMs(num(p.first_token_ms))}`)
      if (num(p.reasoning_tokens)) f.push(`${formatNumber(num(p.reasoning_tokens))} reasoning tokens`)
      if (str(p.reasoning_effort) && p.reasoning_effort !== 'none') f.push(`reasoning ${p.reasoning_effort}`)
      if (str(p.finish_reason)) f.push(`finish: ${p.finish_reason}`)
      break
    case 'compute_route':
      f.push(p.error ? `routing failed: ${p.error}` : p.computation ? `→ ${p.computation}` : 'no computation fits → documents')
      break
    case 'compute':
      f.push(String(p.name ?? ''))
      f.push(p.error ? `failed: ${p.error}` : p.attested ? `attested · ${p.rows} row${p.rows === 1 ? '' : 's'}` : 'failed attestation')
      break
    case 'execution':
      f.push(String(p.status ?? '').replace(/_/g, ' '))
      if (num(p.attempts)) f.push(`${p.attempts} run${p.attempts === 1 ? '' : 's'}`)
      if (str(p.test_source) && p.test_source !== 'none') f.push(`tests: ${p.test_source}`)
      break
    case 'okf_policy':
      f.push(`${p.dropped ?? 0} stale left out · ${p.demoted ?? 0} deprecated demoted`)
      break
    case 'output_validation':
      f.push(num(p.removed) ? `removed ${p.removed} unsourced link${p.removed === 1 ? '' : 's'} / contact${p.removed === 1 ? '' : 's'}` : 'nothing to remove')
      break
    case 'cache_lookup':
      f.push(p.hit ? 'hit' : p.guard_blocked ? 'miss — similar question, but its numbers or identifiers differ' : 'miss')
      if (num(p.similarity) != null) f.push(`best ${Math.round(num(p.similarity)! * 100)}% (needs ${Math.round(num(p.threshold)! * 100)}%)`)
      if (num(p.entries) != null) f.push(`${p.entries} cached`)
      break
    case 'agent':
      if (p.cached) {
        f.push(`cached agent run · ${p.steps} step${p.steps === 1 ? '' : 's'}`)
        break
      }
      if (num(p.turn) != null) f.push(`step ${p.turn}`)
      if (p.action === 'search' && Array.isArray(p.queries)) f.push(`search: ${(p.queries as string[]).map((q) => `“${q}”`).join(', ') || 'nothing new'}`)
      else if (p.action === 'read') f.push(`read ${p.read} passage${p.read === 1 ? '' : 's'} in full`)
      else if (p.action === 'done') f.push(p.invalid_reply ? 'unusable reply → kept search order' : `kept ${p.keep}`)
      else if (p.action === 'error') f.push('planner call failed → kept search order')
      if (num(p.context_chars) != null) f.push(`${formatNumber(Math.round(num(p.context_chars)! / 4))} tok context${p.offload ? ' (offloaded)' : ''}`)
      break
    case 'verify':
      if (p.status === 'error') f.push('check failed')
      else {
        if (num(p.claims) != null) f.push(`${p.claims} claim${p.claims === 1 ? '' : 's'}`)
        if (num(p.unsupported)) f.push(`${p.unsupported} not supported`)
        if (typeof p.grounded === 'boolean') f.push(p.grounded ? 'grounded' : 'not grounded')
      }
      break
    default:
      for (const [k, v] of Object.entries(p)) {
        if (f.length >= 3) break
        if (['string', 'number', 'boolean'].includes(typeof v)) f.push(`${k.replace(/_/g, ' ')} ${String(v)}`)
      }
  }
  return f
}

const tokens = (a: number, b: number) => (a || b ? `${a ? formatNumber(a) : '—'} / ${b ? formatNumber(b) : '—'}` : '—')
// `priced: false` = an LLM call whose model has no known list price: "—", never "$0".
const unpriced = (s: TraceStep) => s.payload?.priced === false
const cost = (c: number, s: TraceStep) => (!unpriced(s) && (c || s.tokens_in || s.tokens_out) ? formatCost(c) : '—')
const COST_NOTE = 'paid-tier list price (free tiers cost $0); "—" = no published price for this model.'

export function TracePanel({ turn, indexType }: { turn: Turn; indexType?: string }) {
  const active = isActive(turn)
  const steps = [...turn.trace].sort((a, b) => a.seq - b.seq)
  const gen = steps.find((s) => s.step === 'generate')
  const dense = steps.find((s) => s.step === 'dense_search')
  const exact = typeof dense?.payload?.exact === 'boolean' ? (dense.payload.exact as boolean) : undefined
  const maxMs = Math.max(1, ...steps.map((s) => s.ms))
  // Waterfall when every step has a start offset (concurrent steps overlap); plain duration bars otherwise.
  const timed = steps.every((s) => typeof s.start_ms === 'number')
  const span = timed ? Math.max(1, ...steps.map((s) => (s.start_ms ?? 0) + s.ms)) : maxMs
  const sumMs = steps.reduce((a, s) => a + s.ms, 0)
  const tin = steps.reduce((a, s) => a + s.tokens_in, 0)
  const tout = steps.reduce((a, s) => a + s.tokens_out, 0)
  const tcost = steps.reduce((a, s) => a + s.cost_usd, 0)
  const costKnown = !steps.some(unpriced)
  const firstToken = num(gen?.payload?.first_token_ms) ?? (turn.firstTokenAt ? turn.firstTokenAt - turn.startedAt : undefined)
  const total = turn.totals?.latency_ms ?? turn.totals?.ms ?? (turn.endedAt ? turn.endedAt - turn.startedAt : undefined)
  const store = turn.store ?? str(dense?.payload?.store)
  const run = useRun(!active && turn.runId ? turn.runId : null)
  const messages = (run.data?.result?.messages ?? []) as { role?: string; content?: unknown }[]
  const prompt = messages
    .map((m) => `── ${m.role ?? 'message'} ──\n${typeof m.content === 'string' ? m.content : JSON.stringify(m.content, null, 2)}`)
    .join('\n\n')

  if (!steps.length) {
    return (
      <p className="flex items-center gap-2 py-8 text-body text-text-secondary">
        {active ? <><Spinner size={14} /> Waiting for the retrieval trace…</> : 'No trace was recorded for this question.'}
      </p>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {store && (
          <ExactBadge
            exact={exact ?? true}
            label={[storeLabel(store), indexType, exact == null ? undefined : exact ? 'exact' : 'approximate'].filter(Boolean).join(' · ')}
          />
        )}
        {turn.version != null && <span className="text-body-sm text-text-tertiary">v{turn.version}</span>}
        {turn.runId && (
          <span className="ml-auto inline-flex items-center gap-1 text-body-sm text-text-tertiary">
            run id <code className="font-mono text-mono-sm text-text-secondary">{shortHash(turn.runId, 8)}…</code>
            <CopyButton text={turn.runId} aria-label="Copy run id" />
          </span>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Total" value={total != null ? formatMs(total) : active ? '…' : '—'} />
        <Stat label="First token" value={firstToken != null ? formatMs(firstToken) : active ? '…' : '—'} />
        <Stat label="Tokens in / out" value={tin || tout ? `${formatNumber(tin)} / ${formatNumber(tout)}` : active ? '…' : '—'} />
        <Stat label="Cost (list price)" value={costKnown && (gen || tcost) ? formatCost(tcost) : active ? '…' : '—'} />
      </dl>

      <div className="overflow-x-auto rounded-lg border border-border-default">
        <table className="w-full border-collapse text-body">
          <caption className="sr-only">Per-step latency, tokens and cost</caption>
          <thead>
            <tr className="h-9 bg-bg-subtle text-left text-caption text-text-tertiary">
              <th scope="col" className="px-3 font-medium">Step</th>
              <th scope="col" className="px-3 font-medium">{timed ? 'ms · timeline' : 'ms'}</th>
              <th scope="col" className="whitespace-nowrap px-3 text-right font-medium">Tokens in / out</th>
              <th scope="col" className="hidden px-3 text-right font-medium sm:table-cell">Cost</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((s) => {
              const facts = payloadFacts(s)
              const isGen = s.step === 'generate'
              return (
                <tr key={`${s.seq}-${s.step}`} className="border-t border-border-default align-top">
                  <td className="px-3 py-2">
                    <div className="font-mono text-mono text-text-primary">{s.step}</div>
                    {facts.length > 0 && <div className="mt-0.5 text-body-sm text-text-tertiary">{facts.join(' · ')}</div>}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="w-11 shrink-0 text-right sm:w-14 font-mono text-mono tabular-nums text-text-primary">{formatNumber(Math.round(s.ms))}</span>
                      <span
                        className="hidden h-1.5 w-full max-w-56 min-w-10 rounded-full bg-bg-muted sm:block"
                        aria-hidden
                        title={timed ? `starts at ${formatMs(s.start_ms ?? 0)}, takes ${formatMs(s.ms)}` : undefined}
                      >
                        <span
                          className={cn('block h-full rounded-full', isGen ? 'bg-accent-default' : 'bg-accent-default/30')}
                          style={{
                            marginLeft: timed ? `${((s.start_ms ?? 0) / span) * 100}%` : undefined,
                            width: `${Math.max(timed ? 1 : 2, (s.ms / span) * 100)}%`,
                          }}
                        />
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-mono tabular-nums text-text-secondary">{tokens(s.tokens_in, s.tokens_out)}</td>
                  <td className="hidden px-3 py-2 text-right font-mono text-mono tabular-nums text-text-secondary sm:table-cell">{cost(s.cost_usd, s)}</td>
                </tr>
              )
            })}
            {active && !gen && (
              <tr className="border-t border-border-default">
                <td className="px-3 py-2 font-mono text-mono text-text-primary">generate</td>
                <td colSpan={3} className="px-3 py-2 text-body-sm text-text-secondary">
                  <span className="inline-flex items-center gap-2"><Spinner size={12} /> Waiting for the model…</span>
                </td>
              </tr>
            )}
            <tr className="border-t border-border-default bg-bg-subtle font-semibold">
              <td className="px-3 py-2 text-label">Total</td>
              <td className="px-3 py-2">
                <span className="inline-block w-11 text-right sm:w-14 font-mono text-mono tabular-nums">{formatNumber(Math.round(sumMs))}</span>
              </td>
              <td className="px-3 py-2 text-right font-mono text-mono tabular-nums">{tokens(tin, tout)}</td>
              <td className="hidden px-3 py-2 text-right font-mono text-mono tabular-nums sm:table-cell">{gen && costKnown ? formatCost(tcost) : '—'}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {gen && <p className="text-body-sm text-text-tertiary">Cost: {COST_NOTE}</p>}
      {total != null && sumMs > 0 && Math.abs(total - sumMs) > 50 && (
        <p className="text-body-sm text-text-tertiary">
          Step times add up to {formatMs(sumMs)}; end-to-end latency was {formatMs(total)} (includes streaming and overhead).
        </p>
      )}

      {!active && turn.runId && !turn.cache && !turn.computation?.attested && (
        <Disclosure label="Prompt sent to model" hint={messages.length ? `${messages.length} messages` : undefined}>
          {run.isPending ? (
            <p className="flex items-center gap-2 text-body-sm text-text-secondary"><Spinner size={12} /> Loading prompt…</p>
          ) : prompt ? (
            <CodeBlock code={prompt} wrap maxHeight={360} />
          ) : (
            <p className="text-body-sm text-text-secondary">The prompt wasn't recorded for this run.</p>
          )}
        </Disclosure>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-default bg-bg-surface px-3 py-2">
      <dt className="text-caption text-text-tertiary">{label}</dt>
      <dd className="mt-0.5 font-mono text-mono tabular-nums text-text-primary">{value}</dd>
    </div>
  )
}
