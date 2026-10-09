import { ShieldAlert, ShieldCheck } from 'lucide-react'
import type { ComputeReceipt } from '@/api/types'
import { Badge, CodeBlock, Disclosure, cn } from '@/components/ui'

const cell = (v: unknown) => (v === null || v === undefined ? '∅' : typeof v === 'number' ? v.toLocaleString() : String(v))

/** What a computation did: parameters, the read-only SQL, the result and every attestation check. */
export function Receipt({ r, compact }: { r: ComputeReceipt; compact?: boolean }) {
  const params = Object.entries(r.parameters ?? {}).filter(([, v]) => v !== null && v !== undefined)
  const rows = r.result?.rows ?? []
  return (
    <div className={cn('flex flex-col gap-2 rounded-lg border p-3 text-body-sm', r.attested ? 'border-success-border bg-success-bg/40' : 'border-warning-border bg-warning-bg/40')}>
      <p className="flex flex-wrap items-center gap-2">
        {r.attested ? <ShieldCheck size={14} aria-hidden className="text-success-fg" /> : <ShieldAlert size={14} aria-hidden className="text-warning-fg" />}
        <span className="font-medium text-text-primary">{r.name}</span>
        <Badge tone={r.attested ? 'success' : 'warning'}>{r.attested ? 'computed · attested' : r.error ? 'failed' : 'failed attestation'}</Badge>
        {params.length > 0 && <span className="text-text-tertiary">{params.map(([k, v]) => `${k} = ${String(v)}`).join(' · ')}</span>}
        {r.result && <span className="ml-auto font-mono text-mono-sm text-text-tertiary">{r.result.ms} ms · read-only</span>}
      </p>
      {r.error && <p className="text-warning-fg">{r.error}</p>}
      {r.checks.length > 0 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {r.checks.map((c) => (
            <li key={c.check} className={cn('font-mono text-mono-sm', c.ok ? 'text-success-fg' : 'text-danger-fg')} title={c.detail}>
              {c.ok ? '✓' : '✗'} {c.check}<span className="font-sans text-text-tertiary"> — {c.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {!compact && rows.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-border-default bg-bg-surface">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="bg-bg-subtle text-caption text-text-tertiary">
                {r.result!.columns.map((c) => <th key={c} scope="col" className="px-2 py-1 font-medium">{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 20).map((row, i) => (
                <tr key={i} className="border-t border-border-default">
                  {row.map((v, j) => <td key={j} className="px-2 py-1 font-mono text-mono-sm tabular-nums text-text-primary">{cell(v)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 20 && <p className="px-2 py-1 text-caption text-text-tertiary">…{rows.length - 20} more rows</p>}
        </div>
      )}
      <Disclosure label="SQL that ran">
        <CodeBlock code={r.sql} wrap />
      </Disclosure>
    </div>
  )
}
