import { useState } from 'react'
import { ArrowRight } from 'lucide-react'
import { formatValue } from '@/api/format'
import type { Change, SlotCatalog } from '@/api/types'
import { Button, EffectBadge, cn } from '@/components/ui'

const isLong = (v: unknown) => typeof v === 'string' && (v.includes('\n') || v.length > 48)

function show(v: unknown): string {
  if (v === '') return '(empty)'
  if (v === null || v === undefined) return 'none'
  if (Array.isArray(v)) return JSON.stringify(v)
  return formatValue(v)
}

type Line = { t: ' ' | '+' | '-'; s: string }

/** Minimal line diff (LCS) for prompt-sized text. */
function lineDiff(a: string, b: string): Line[] {
  const x = a.split('\n')
  const y = b.split('\n')
  const n = x.length
  const m = y.length
  if (n * m > 250_000) return [...x.map((s) => ({ t: '-' as const, s })), ...y.map((s) => ({ t: '+' as const, s }))]
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const out: Line[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      out.push({ t: ' ', s: x[i] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ t: '-', s: x[i++] })
    else out.push({ t: '+', s: y[j++] })
  }
  while (i < n) out.push({ t: '-', s: x[i++] })
  while (j < m) out.push({ t: '+', s: y[j++] })
  return out
}

function TextChange({ before, after }: { before: unknown; after: unknown }) {
  const [open, setOpen] = useState(false)
  const a = typeof before === 'string' ? before : show(before)
  const b = typeof after === 'string' ? after : show(after)
  const delta = b.split('\n').length - a.split('\n').length
  const summary = delta > 0 ? `edited (+${delta} line${delta === 1 ? '' : 's'})` : delta < 0 ? `edited (−${-delta} line${delta === -1 ? '' : 's'})` : 'edited'
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="font-mono text-mono text-text-primary">{summary}</span>
        <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Hide' : 'Show'}
        </Button>
      </div>
      {open && (
        <pre className="max-h-72 overflow-auto rounded-md bg-bg-code p-3 font-mono text-mono text-text-code">
          {lineDiff(a, b).map((l, i) => (
            <div
              key={i}
              className={cn('whitespace-pre-wrap', l.t === '+' && 'bg-success-fg/20', l.t === '-' && 'bg-danger-fg/20 line-through opacity-70')}
            >
              <span aria-hidden className="mr-2 select-none opacity-60">{l.t}</span>
              <span className="sr-only">{l.t === '+' ? 'added: ' : l.t === '-' ? 'removed: ' : ''}</span>
              {l.s || ' '}
            </div>
          ))}
        </pre>
      )}
    </div>
  )
}

/** `Stage · field: before → after [effect]` rows. */
export function DiffTable({ changes, catalog }: { changes: Change[]; catalog?: SlotCatalog[] }) {
  if (!changes.length) {
    return <p className="text-body text-text-tertiary">No configuration changes — identical pipelines.</p>
  }
  return (
    <ul className="overflow-hidden rounded-lg border border-border-default" aria-label="Configuration changes">
      {changes.map((c, i) => {
        const sc = catalog?.find((s) => s.slot === c.slot)
        const nt = sc?.types.find((t) => t.type === (c.field === 'type' ? c.after : undefined)) ?? sc?.types.find((t) => c.field in (t.schema.properties ?? {}))
        const fieldTitle = c.field === 'type' ? 'Type' : (nt?.schema.properties?.[c.field]?.title ?? c.field)
        return (
          <li
            key={`${c.slot}.${c.field}.${i}`}
            className="flex flex-col gap-2 border-b border-border-default px-3 py-2.5 last:border-b-0 sm:flex-row sm:items-start sm:gap-4"
          >
            <span className="shrink-0 font-mono text-mono text-text-secondary sm:w-56" title={`${sc?.title ?? c.slot} · ${fieldTitle}`}>
              {sc?.title ?? c.slot} · {c.field}
            </span>
            <span className="min-w-0 flex-1">
              {isLong(c.before) || isLong(c.after) ? (
                <TextChange before={c.before} after={c.after} />
              ) : (
                <span className="flex flex-wrap items-center gap-1.5 font-mono text-mono">
                  <s className="break-all text-text-tertiary">{show(c.before)}</s>
                  <ArrowRight size={12} aria-label="changed to" className="shrink-0 text-text-tertiary" />
                  <span className="break-all text-text-primary">{show(c.after)}</span>
                </span>
              )}
            </span>
            <EffectBadge effect={c.effect} className="self-start" />
          </li>
        )
      })}
    </ul>
  )
}
