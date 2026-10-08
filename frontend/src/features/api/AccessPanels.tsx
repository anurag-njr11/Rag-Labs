import { useState } from 'react'
import { BarChart3, KeyRound } from 'lucide-react'
import { errorMessage, useApiKeys, useCreateApiKey, useRevokeApiKey, useUsage } from '@/api/hooks'
import { formatCost, formatMs, formatNumber } from '@/api/format'
import type { UsageReport } from '@/api/types'
import { Badge, Banner, Button, Card, CopyButton, Input, Select, cn, useToast } from '@/components/ui'

/** FR-3.23: keys for callers outside this machine. The web UI on this machine needs none. */
export function KeysPanel({ projectId }: { projectId: string }) {
  const keys = useApiKeys()
  const create = useCreateApiKey()
  const revoke = useRevokeApiKey()
  const { toast } = useToast()
  const [name, setName] = useState('')
  const [scope, setScope] = useState<'chat' | 'admin'>('chat')
  const [made, setMade] = useState<string | null>(null)
  const mine = (keys.data ?? []).filter((k) => k.scope === 'admin' || k.project_id === projectId)

  const add = () =>
    create.mutate({ name: name.trim(), scope, project_id: scope === 'chat' ? projectId : undefined }, {
      onSuccess: (k) => { setMade(k.key); setName('') },
      onError: (e) => toast({ tone: 'danger', title: 'Could not create the key', description: errorMessage(e) }),
    })

  return (
    <Card padding="lg" className="space-y-4">
      <div>
        <h2 className="flex items-center gap-2 text-heading text-text-primary"><KeyRound size={18} aria-hidden /> API keys</h2>
        <p className="mt-1 text-body text-text-secondary">
          Requests from this machine need no key. Anything else must send <code className="font-mono text-mono">Authorization: Bearer rl_…</code>.
          A <strong>chat</strong> key may only call this project's query endpoint; an <strong>admin</strong> key may call the whole API. Only a
          hash is stored — copy the key when it's shown.
        </p>
      </div>
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); add() }}>
        <Input aria-label="Key name" placeholder="Name, e.g. support website" value={name} maxLength={80}
          onChange={(e) => setName(e.target.value)} wrapperClassName="min-w-56 flex-1" />
        <Select aria-label="Key scope" value={scope} onChange={(e) => setScope(e.target.value as 'chat' | 'admin')}
          options={[{ value: 'chat', label: 'Chat — this project only' }, { value: 'admin', label: 'Admin — whole API' }]} />
        <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>Create key</Button>
      </form>
      {made && (
        <Banner tone="success" title="Copy it now — it won't be shown again."
          actions={<Button size="sm" onClick={() => setMade(null)}>Done</Button>}>
          <span className="flex min-w-0 items-center gap-2">
            <code className="min-w-0 flex-1 truncate font-mono text-mono">{made}</code>
            <CopyButton text={made} aria-label="Copy API key" />
          </span>
        </Banner>
      )}
      {mine.length > 0 && (
        <ul className="divide-y divide-border-default rounded-lg border border-border-default">
          {mine.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-body-sm">
              <span className="text-text-primary">{k.name}</span>
              <code className="font-mono text-mono-sm text-text-tertiary">{k.prefix}…</code>
              <Badge tone={k.scope === 'admin' ? 'warning' : 'neutral'}>{k.scope}</Badge>
              {k.revoked_at && <Badge tone="danger">revoked</Badge>}
              <span className="ml-auto text-text-tertiary">
                {k.last_used_at ? `last used ${new Date(k.last_used_at).toLocaleString()}` : 'never used'}
              </span>
              {!k.revoked_at && (
                <Button size="sm" variant="ghost" onClick={() => revoke.mutate(k.id)} aria-label={`Revoke ${k.name}`}>Revoke</Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border-default bg-bg-surface px-3 py-2">
      <dt className="text-caption text-text-tertiary">{label}</dt>
      <dd className="mt-0.5 font-mono text-mono tabular-nums text-text-primary">{value}</dd>
      {hint && <dd className="text-caption text-text-tertiary">{hint}</dd>}
    </div>
  )
}

/** Daily requests: one series, so no legend; hover any bar for its numbers; a table for screen readers. */
function DailyBars({ u }: { u: UsageReport }) {
  const [hover, setHover] = useState<number | null>(null)
  const [now] = useState(() => Date.now())
  const days = Array.from({ length: u.days }, (_, i) => {
    const d = new Date(now - (u.days - 1 - i) * 86_400_000).toISOString().slice(0, 10)
    return u.daily.find((x) => x.day === d) ?? { day: d, requests: 0, errors: 0, tokens_in: 0, tokens_out: 0, cost_usd: 0, api: 0 }
  })
  const W = 720, H = 140, B = 20, max = Math.max(1, ...days.map((d) => d.requests))
  const bw = W / days.length
  const h = hover != null ? days[hover] : null
  return (
    <figure className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`Requests per day, last ${u.days} days`}>
        <line x1={0} x2={W} y1={H - B} y2={H - B} className="stroke-border-default" />
        {days.map((d, i) => {
          const bh = (d.requests / max) * (H - B - 8)
          return (
            <g key={d.day} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={i * bw} y={0} width={bw} height={H - B} fill="transparent" />
              {d.requests > 0 && (
                <rect x={i * bw + bw * 0.2} y={H - B - bh} width={Math.max(2, bw * 0.6)} height={bh} rx={Math.min(4, bw * 0.3)}
                  className={cn('fill-accent-default', hover === i ? 'opacity-100' : 'opacity-80')} />
              )}
            </g>
          )
        })}
        <text x={0} y={H - 4} className="fill-text-tertiary text-[11px]">{days[0].day.slice(5)}</text>
        <text x={W} y={H - 4} textAnchor="end" className="fill-text-tertiary text-[11px]">today</text>
        <text x={0} y={10} className="fill-text-tertiary text-[11px]">{formatNumber(max)}</text>
      </svg>
      {h && (
        <div role="tooltip" className="pointer-events-none absolute top-0 rounded-md border border-border-default bg-bg-surface px-2 py-1 text-body-sm shadow-lg"
          style={{ left: `${Math.min(80, (hover! / days.length) * 100)}%` }}>
          <p className="font-medium text-text-primary">{h.day}</p>
          <p className="font-mono text-mono-sm text-text-secondary">
            {formatNumber(h.requests)} requests · {formatNumber(h.api)} API · {formatNumber(h.errors)} errors
          </p>
        </div>
      )}
      <table className="sr-only">
        <caption>Requests per day</caption>
        <thead><tr><th>Day</th><th>Requests</th><th>Errors</th></tr></thead>
        <tbody>{days.filter((d) => d.requests).map((d) => <tr key={d.day}><td>{d.day}</td><td>{d.requests}</td><td>{d.errors}</td></tr>)}</tbody>
      </table>
    </figure>
  )
}

export function UsagePanel({ projectId }: { projectId: string }) {
  const [days, setDays] = useState(30)
  const q = useUsage(projectId, days)
  const u = q.data
  return (
    <Card padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="flex items-center gap-2 text-heading text-text-primary"><BarChart3 size={18} aria-hidden /> Usage</h2>
        <Select aria-label="Period" value={String(days)} onChange={(e) => setDays(Number(e.target.value))} wrapperClassName="ml-auto"
          options={[{ value: '7', label: 'Last 7 days' }, { value: '30', label: 'Last 30 days' }, { value: '90', label: 'Last 90 days' }]} />
      </div>
      {u && (
        <>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Requests" value={formatNumber(u.total.requests)} hint={`${formatNumber(u.total.api)} API · ${formatNumber(u.total.playground)} Playground`} />
            <Stat label="Errors" value={u.total.requests ? `${Math.round((u.total.errors / u.total.requests) * 100)}%` : '—'} hint={`${formatNumber(u.total.errors)} failed`} />
            <Stat label="Latency p50" value={u.latency.p50_ms != null ? formatMs(u.latency.p50_ms) : '—'} hint={u.latency.p95_ms != null ? `p95 ${formatMs(u.latency.p95_ms)}` : undefined} />
            <Stat label="Tokens · cost" value={`${formatNumber(u.total.tokens_in + u.total.tokens_out)}`} hint={`${formatCost(u.total.cost_usd)} at list price`} />
          </dl>
          {u.total.requests > 0 ? <DailyBars u={u} /> : <p className="text-body-sm text-text-tertiary">No requests in this period.</p>}
          {u.by_key.length > 0 && (
            <p className="text-body-sm text-text-secondary">
              By key: {u.by_key.map((k) => `${k.name} (${k.prefix}…) ${formatNumber(k.requests)}`).join(' · ')}
            </p>
          )}
        </>
      )}
    </Card>
  )
}
