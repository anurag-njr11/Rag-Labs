import { useRef, useState } from 'react'
import { Calculator, Plus, Table2, Trash2, Upload } from 'lucide-react'
import {
  errorMessage, useComputations, useDataTables, useDeleteComputation, useDeleteTable, useRunComputation,
  useSaveComputation, useUploadTables,
} from '@/api/hooks'
import { formatNumber } from '@/api/format'
import type { Computation, ComputationParam, ComputationSpec, ComputeReceipt } from '@/api/types'
import { projectPath, useWorkspace } from '@/app/workspace'
import { Badge, Banner, Button, ButtonLink, Card, EmptyState, Field, Input, Select, Switch, Textarea, useToast } from '@/components/ui'
import { Receipt } from './Receipt'

const EMPTY: ComputationSpec = {
  name: '', description: '', unit: '', sql: 'SELECT ',
  parameters: [],
  attester: { min_rows: 1, max_rows: 1, columns: [], non_null: true, bounds: {} },
}
const PARAM: ComputationParam = { name: '', type: 'string', required: true, description: '', options: null }
const list = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)

/** FR-3.21: data tables + sanctioned, attested computations over them. */
export default function DataTab() {
  const { project } = useWorkspace()
  const pid = project.id
  const computeOn = (project.active_version?.config?.compute as { type?: string } | undefined)?.type === 'attested'
  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 px-4 py-8 sm:px-8">
      <div className="max-w-3xl">
        <h2 className="text-title-lg text-text-primary">Data &amp; computations</h2>
        <p className="mt-1 text-body-lg text-text-secondary">
          Numbers should come from your data, not from a slide that may be out of date. Upload tables, define the computations
          the assistant may run — a read-only SQL query with typed parameters and checks its result must pass — and numeric
          questions are answered exactly as computed, with a receipt. The model only picks a computation and fills in its
          parameters; it can never write a query.
        </p>
      </div>
      {!computeOn && (
        <Banner tone="info" title="Not used in answers yet."
          actions={<ButtonLink to={projectPath(pid, 'configure')} size="sm" variant="secondary">Configure</ButtonLink>}>
          Turn it on in Configure › Compute › Attested computations (it applies to the version you save).
        </Banner>
      )}
      <Tables projectId={pid} />
      <Computations projectId={pid} />
    </div>
  )
}

function Tables({ projectId }: { projectId: string }) {
  const tables = useDataTables(projectId)
  const upload = useUploadTables(projectId)
  const del = useDeleteTable(projectId)
  const { toast } = useToast()
  const input = useRef<HTMLInputElement>(null)
  const pick = (files: FileList | null) => {
    if (!files?.length) return
    upload.mutate(Array.from(files), {
      onSuccess: (r) => toast({
        tone: r.errors.length ? 'warning' : 'success',
        title: `Loaded ${r.created.length} table${r.created.length === 1 ? '' : 's'}`,
        description: [...r.created.map((t) => `${t.table}: ${formatNumber(t.rows)} rows`), ...r.errors.map((e) => `${e.filename}: ${e.error}`)].join(' · '),
      }),
      onError: (e) => toast({ tone: 'danger', title: 'Upload failed', description: errorMessage(e) }),
    })
  }
  return (
    <Card padding="lg" className="flex flex-col gap-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="flex items-center gap-2 text-heading-lg text-text-primary"><Table2 size={18} aria-hidden /> Tables</h3>
        <span className="text-body-sm text-text-tertiary">CSV or TSV; column types are inferred. A file replaces the table of the same name.</span>
        <Button variant="primary" className="ml-auto" icon={<Upload size={14} aria-hidden />} loading={upload.isPending} onClick={() => input.current?.click()}>
          Upload CSV
        </Button>
        <input ref={input} type="file" accept=".csv,.tsv,text/csv" multiple hidden aria-hidden tabIndex={-1}
          onChange={(e) => { pick(e.target.files); e.target.value = '' }} />
      </div>
      {tables.data && tables.data.length === 0 && (
        <EmptyState icon={<Table2 aria-hidden />} title="No tables yet" description="Upload a CSV — e.g. sales by region and quarter." />
      )}
      {(tables.data ?? []).map((t) => (
        <div key={t.table} className="flex flex-wrap items-center gap-2 border-t border-border-default pt-3">
          <span className="font-mono text-mono text-text-primary">{t.table}</span>
          <span className="text-body-sm text-text-tertiary">{formatNumber(t.rows)} rows</span>
          <span className="flex flex-wrap gap-1">
            {t.columns.map((c) => <Badge key={c.name} tone="neutral"><span className="font-mono">{c.name}</span> {c.type.toLowerCase()}</Badge>)}
          </span>
          <Button size="sm" variant="ghost" className="ml-auto" icon={<Trash2 size={12} aria-hidden />}
            onClick={() => del.mutate(t.table)} aria-label={`Delete table ${t.table}`}>
            Delete
          </Button>
        </div>
      ))}
    </Card>
  )
}

function Computations({ projectId }: { projectId: string }) {
  const comps = useComputations(projectId)
  const del = useDeleteComputation(projectId)
  const [editing, setEditing] = useState<Computation | 'new' | null>(null)
  const [trying, setTrying] = useState<string | null>(null)
  return (
    <Card padding="lg" className="flex flex-col gap-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="flex items-center gap-2 text-heading-lg text-text-primary"><Calculator size={18} aria-hidden /> Computations</h3>
        <Button className="ml-auto" icon={<Plus size={14} aria-hidden />} onClick={() => setEditing('new')} disabled={editing !== null}>
          New computation
        </Button>
      </div>
      {editing && (
        <Editor projectId={projectId} initial={editing === 'new' ? undefined : editing} onDone={() => setEditing(null)} />
      )}
      {comps.data && comps.data.length === 0 && !editing && (
        <EmptyState icon={<Calculator aria-hidden />} title="No computations yet"
          description="Define one per figure people ask for — “quarterly revenue for a region”, “active users last month”." />
      )}
      {(comps.data ?? []).map((c) => (
        <div key={c.id} className="flex flex-col gap-2 border-t border-border-default pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-body text-text-primary">{c.name}</span>
            <span className="text-body-sm text-text-tertiary">{c.description}</span>
            <span className="ml-auto flex gap-1">
              <Button size="sm" variant="secondary" onClick={() => setTrying(trying === c.id ? null : c.id)}>Try it</Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(c)} disabled={editing !== null}>Edit</Button>
              <Button size="sm" variant="ghost" icon={<Trash2 size={12} aria-hidden />} onClick={() => del.mutate(c.id)} aria-label={`Delete ${c.name}`}>Delete</Button>
            </span>
          </div>
          {c.parameters.length > 0 && (
            <p className="text-body-sm text-text-tertiary">
              Parameters: {c.parameters.map((p) => `${p.name} (${p.type}${p.options ? `: ${p.options.join('/')}` : ''})`).join(', ')}
            </p>
          )}
          {trying === c.id && <TryIt projectId={projectId} c={c} />}
        </div>
      ))}
    </Card>
  )
}

function TryIt({ projectId, c }: { projectId: string; c: Computation }) {
  const run = useRunComputation(projectId)
  const [values, setValues] = useState<Record<string, string>>({})
  const [receipt, setReceipt] = useState<ComputeReceipt | null>(null)
  return (
    <div className="flex flex-col gap-3 rounded-lg bg-bg-subtle p-3">
      <div className="flex flex-wrap items-end gap-3">
        {c.parameters.map((p) => (
          <Field key={p.name} label={p.name} help={p.description || p.type}>
            {(f) => p.options ? (
              <Select id={f.id} value={values[p.name] ?? ''} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                options={[{ value: '', label: '—' }, ...p.options.map((o) => ({ value: o, label: o }))]} />
            ) : (
              <Input id={f.id} aria-describedby={f.describedBy} type={p.type === 'date' ? 'date' : p.type === 'string' ? 'text' : 'number'}
                value={values[p.name] ?? ''} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} />
            )}
          </Field>
        ))}
        <Button variant="primary" loading={run.isPending}
          onClick={() => run.mutate({ id: c.id, parameters: values }, { onSuccess: setReceipt, onError: () => setReceipt(null) })}>
          Run
        </Button>
      </div>
      {run.isError && <Banner tone="danger">{errorMessage(run.error)}</Banner>}
      {receipt && <Receipt r={receipt} />}
    </div>
  )
}

function Editor({ projectId, initial, onDone }: { projectId: string; initial?: Computation; onDone: () => void }) {
  const save = useSaveComputation(projectId)
  const { toast } = useToast()
  const [spec, setSpec] = useState<ComputationSpec>(initial ? { ...initial } : EMPTY)
  const set = <K extends keyof ComputationSpec>(k: K, v: ComputationSpec[K]) => setSpec((s) => ({ ...s, [k]: v }))
  const att = spec.attester
  const setAtt = (patch: Partial<ComputationSpec['attester']>) => set('attester', { ...att, ...patch })
  const setParam = (i: number, patch: Partial<ComputationParam>) =>
    set('parameters', spec.parameters.map((p, j) => (j === i ? { ...p, ...patch } : p)))
  const bounds = Object.entries(att.bounds)

  const submit = () =>
    save.mutate({ id: initial?.id, spec }, {
      onSuccess: () => { toast({ tone: 'success', title: `Saved “${spec.name}”` }); onDone() },
    })

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border-default p-4">
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Name">{(f) => <Input id={f.id} value={spec.name} maxLength={80} onChange={(e) => set('name', e.target.value)} />}</Field>
        <Field label="Unit" help="Shown after a single value, e.g. USD">
          {(f) => <Input id={f.id} aria-describedby={f.describedBy} value={spec.unit} maxLength={40} onChange={(e) => set('unit', e.target.value)} />}
        </Field>
      </div>
      <Field label="What it computes" help="The router reads this to decide when to use it — be specific.">
        {(f) => <Input id={f.id} aria-describedby={f.describedBy} value={spec.description} maxLength={600} onChange={(e) => set('description', e.target.value)} />}
      </Field>
      <Field label="SQL" help="One SELECT (or WITH … SELECT), read-only. Parameters as :name.">
        {(f) => <Textarea id={f.id} aria-describedby={f.describedBy} rows={4} className="font-mono" value={spec.sql} onChange={(e) => set('sql', e.target.value)} />}
      </Field>

      <div className="flex flex-col gap-2">
        <p className="text-label text-text-secondary">Parameters</p>
        {spec.parameters.map((p, i) => (
          <div key={i} className="grid items-end gap-2 sm:grid-cols-[1fr_8rem_1fr_1.5fr_auto_auto]">
            <Field label="Name">{(f) => <Input id={f.id} className="font-mono" value={p.name} onChange={(e) => setParam(i, { name: e.target.value })} />}</Field>
            <Field label="Type">
              {(f) => <Select id={f.id} value={p.type} onChange={(e) => setParam(i, { type: e.target.value as ComputationParam['type'] })}
                options={['string', 'integer', 'number', 'date'].map((t) => ({ value: t, label: t }))} />}
            </Field>
            <Field label="Allowed values" help="comma-separated; empty = any">
              {(f) => <Input id={f.id} value={(p.options ?? []).join(', ')} onChange={(e) => setParam(i, { options: list(e.target.value).length ? list(e.target.value) : null })} />}
            </Field>
            <Field label="Description">{(f) => <Input id={f.id} value={p.description} onChange={(e) => setParam(i, { description: e.target.value })} />}</Field>
            <label className="flex items-center gap-2 pb-2 text-body-sm text-text-secondary">
              <Switch checked={p.required} onChange={(v) => setParam(i, { required: v })} aria-label={`${p.name || 'Parameter'} required`} /> required
            </label>
            <Button size="sm" variant="ghost" className="mb-1" onClick={() => set('parameters', spec.parameters.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <Button size="sm" variant="ghost" className="self-start" icon={<Plus size={12} aria-hidden />}
          onClick={() => set('parameters', [...spec.parameters, { ...PARAM }])}>
          Add parameter
        </Button>
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-label text-text-secondary">Attestation — the result must pass every check before anyone sees it</p>
        <div className="grid items-end gap-3 sm:grid-cols-4">
          <Field label="Min rows">{(f) => <Input id={f.id} type="number" min={0} value={att.min_rows} onChange={(e) => setAtt({ min_rows: Number(e.target.value) })} />}</Field>
          <Field label="Max rows">{(f) => <Input id={f.id} type="number" min={1} value={att.max_rows} onChange={(e) => setAtt({ max_rows: Number(e.target.value) })} />}</Field>
          <Field label="Columns" help="expected, in order">
            {(f) => <Input id={f.id} className="font-mono" value={att.columns.join(', ')} onChange={(e) => setAtt({ columns: list(e.target.value) })} />}
          </Field>
          <label className="flex items-center gap-2 pb-2 text-body-sm text-text-secondary">
            <Switch checked={att.non_null} onChange={(v) => setAtt({ non_null: v })} aria-label="No empty values" /> no empty values
          </label>
        </div>
        {bounds.map(([col, [lo, hi]], i) => (
          <div key={i} className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
            <Field label="Column">{(f) => <Input id={f.id} className="font-mono" value={col}
              onChange={(e) => setAtt({ bounds: Object.fromEntries(bounds.map(([c, b], j) => [j === i ? e.target.value : c, b])) })} />}</Field>
            <Field label="Min">{(f) => <Input id={f.id} type="number" value={lo ?? ''}
              onChange={(e) => setAtt({ bounds: { ...att.bounds, [col]: [e.target.value === '' ? null : Number(e.target.value), hi] } })} />}</Field>
            <Field label="Max">{(f) => <Input id={f.id} type="number" value={hi ?? ''}
              onChange={(e) => setAtt({ bounds: { ...att.bounds, [col]: [lo, e.target.value === '' ? null : Number(e.target.value)] } })} />}</Field>
            <Button size="sm" variant="ghost" className="mb-1"
              onClick={() => setAtt({ bounds: Object.fromEntries(bounds.filter((_, j) => j !== i)) })}>Remove</Button>
          </div>
        ))}
        <Button size="sm" variant="ghost" className="self-start" icon={<Plus size={12} aria-hidden />}
          onClick={() => setAtt({ bounds: { ...att.bounds, [`column_${bounds.length + 1}`]: [null, null] } })}>
          Add a numeric range check
        </Button>
      </div>

      {save.isError && <Banner tone="danger" title="Not saved">{errorMessage(save.error)}</Banner>}
      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>Cancel</Button>
        <Button variant="primary" loading={save.isPending} onClick={submit} disabled={!spec.name.trim() || !spec.description.trim()}>
          Save
        </Button>
      </div>
    </div>
  )
}
