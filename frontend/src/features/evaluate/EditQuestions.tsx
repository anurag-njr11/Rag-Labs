import { useRef, useState } from 'react'
import { Download, Pencil, Plus, RotateCcw, Trash2, Upload, X } from 'lucide-react'
import {
  errorMessage, evalSetCsvUrl, useAddEvalItem, useDeleteEvalItem, useDocuments, useImportEvalCsv, useUpdateEvalItem,
} from '@/api/hooks'
import type { EvalItem, EvalSetDetail } from '@/api/types'
import { Badge, Button, Dialog, Field, Input, Select, Textarea, buttonClasses, cn, useToast } from '@/components/ui'

interface Draft {
  question: string
  gold_answer: string
  evidence: string
  document_id: string
  /** Required facts, `|`-separated while editing (same as the CSV column). */
  facets: string
  /** Python asserts for code answers (FR-3.17); '' = none. */
  tests: string
}

const splitFacets = (s: string) => s.split('|').map((f) => f.trim()).filter(Boolean)

/** Question / answer / document / verbatim evidence form, shared by add and edit. */
function ItemForm({
  initial, documents, lockDocument, onSave, onCancel, saving, error,
}: {
  initial: Draft
  documents: { value: string; label: string }[]
  lockDocument?: boolean
  onSave: (d: Draft) => void
  onCancel: () => void
  saving: boolean
  error: string | null
}) {
  const [d, setD] = useState(initial)
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value })
  return (
    <form
      className="flex flex-col gap-3 rounded-lg border border-border-default bg-bg-subtle p-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSave(d)
      }}
    >
      <Field label="Question">{(f) => <Input id={f.id} value={d.question} onChange={set('question')} required minLength={3} />}</Field>
      <Field label="Expected answer">{(f) => <Input id={f.id} value={d.gold_answer} onChange={set('gold_answer')} required />}</Field>
      {!lockDocument && (
        <Field label="Document">
          {(f) => <Select id={f.id} options={documents} value={d.document_id} onChange={set('document_id')} required />}
        </Field>
      )}
      <Field label="Evidence" help="A sentence copied word for word from that document. A retrieved chunk containing it counts as a hit." error={error}>
        {(f) => <Textarea id={f.id} rows={3} value={d.evidence} onChange={set('evidence')} required aria-describedby={f.describedBy} invalid={f.invalid} />}
      </Field>
      <Field label="Required facts (optional)" help="Short facts a complete answer must state, separated by |. Answer grading flags answers that leave one out.">
        {(f) => <Input id={f.id} value={d.facets} onChange={set('facets')} placeholder="3 retries | exponential backoff" aria-describedby={f.describedBy} />}
      </Field>
      <Field label="Tests (optional, for code answers)" help="Python asserts the answer's code must pass, e.g. from the library's own test suite. Run in a Docker sandbox; scored as execution-verified correctness.">
        {(f) => <Textarea id={f.id} rows={3} className="font-mono" value={d.tests} onChange={set('tests')} placeholder="assert add(2, 3) == 5" aria-describedby={f.describedBy} />}
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" variant="primary" loading={saving}>Save</Button>
      </div>
    </form>
  )
}

function Row({ projectId, setId, item }: { projectId: string; setId: string; item: EvalItem }) {
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const update = useUpdateEvalItem(projectId, setId)
  const del = useDeleteEvalItem(projectId, setId)
  const { toast } = useToast()
  const fail = (title: string) => (e: unknown) => toast({ tone: 'danger', title, description: errorMessage(e) })

  if (editing) {
    return (
      <li className="py-2">
        <ItemForm
          initial={{ question: item.question, gold_answer: item.gold_answer, evidence: item.evidence, document_id: item.document_id, facets: (item.facets ?? []).join(' | '), tests: item.tests ?? '' }}
          documents={[]}
          lockDocument
          saving={update.isPending}
          error={error}
          onCancel={() => setEditing(false)}
          onSave={(d) =>
            update.mutate(
              { itemId: item.id, question: d.question, gold_answer: d.gold_answer, evidence: d.evidence, facets: splitFacets(d.facets), tests: d.tests },
              { onSuccess: () => setEditing(false), onError: (e) => setError(errorMessage(e)) },
            )
          }
        />
      </li>
    )
  }
  return (
    <li className={cn('flex items-start gap-3 border-b border-border-default py-2.5 last:border-b-0', !item.valid && 'opacity-60')}>
      <div className="min-w-0 flex-1">
        <p className="text-body text-text-primary">{item.question}</p>
        <p className="truncate text-body-sm text-text-tertiary">
          {item.document ?? '—'} · {item.gold_answer}
          {item.facets?.length ? ` · ${item.facets.length} required fact${item.facets.length === 1 ? '' : 's'}` : ''}
        </p>
        {!item.valid && item.reject_reason && <p className="text-body-sm text-warning-fg">{item.reject_reason}</p>}
      </div>
      {!item.valid && <Badge tone="warning">dropped</Badge>}
      <div className="flex shrink-0 gap-1">
        <Button size="sm" variant="ghost" iconOnly aria-label="Edit question" icon={<Pencil size={14} aria-hidden />} onClick={() => setEditing(true)} />
        <Button
          size="sm" variant="ghost" iconOnly
          aria-label={item.valid ? 'Drop from scoring' : 'Restore'}
          title={item.valid ? 'Drop from scoring (kept in the list)' : 'Restore'}
          icon={item.valid ? <X size={14} aria-hidden /> : <RotateCcw size={14} aria-hidden />}
          onClick={() => update.mutate({ itemId: item.id, valid: !item.valid }, { onError: fail("Couldn't change it") })}
        />
        <Button
          size="sm" variant="ghost" iconOnly aria-label="Delete question" icon={<Trash2 size={14} aria-hidden />}
          onClick={() => del.mutate(item.id, { onError: fail("Couldn't delete it") })}
        />
      </div>
    </li>
  )
}

/** Hand-edit an eval set (PRD FR-2.4): add, edit, drop/restore, delete; CSV export and import. */
export function EditQuestions({ set }: { set: EvalSetDetail }) {
  const projectId = set.project_id
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const docs = useDocuments(open ? projectId : undefined)
  const add = useAddEvalItem(projectId, set.id)
  const importCsv = useImportEvalCsv(projectId, set.id)
  const { toast } = useToast()
  const file = useRef<HTMLInputElement>(null)
  const documents = (docs.data ?? []).map((d) => ({ value: d.id, label: d.filename }))
  const items = [...set.items].sort((a, b) => Number(b.valid) - Number(a.valid))

  const onFile = async (f: File | undefined) => {
    if (!f) return
    importCsv.mutate(await f.text(), {
      onSuccess: (r) =>
        toast({
          tone: r.error_count || r.skipped ? 'warning' : 'success',
          title: `Imported ${r.added} question${r.added === 1 ? '' : 's'}`,
          description: [
            r.skipped ? `${r.skipped} row(s) over the 500-question limit` : '',
            r.error_count ? `${r.error_count} row(s) skipped — ${r.errors.slice(0, 3).map((e) => `row ${e.row}: ${e.message}`).join('; ')}` : '',
          ].filter(Boolean).join(' · ') || undefined,
        }),
      onError: (e) => toast({ tone: 'danger', title: 'Import failed', description: errorMessage(e) }),
    })
    if (file.current) file.current.value = ''
  }

  return (
    <>
      <Button variant="secondary" icon={<Pencil size={14} aria-hidden />} onClick={() => setOpen(true)}>Edit questions</Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        size="xl"
        title="Edit eval questions"
        description="Changes apply to the next evaluation run; earlier runs keep the questions they were scored on."
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={<Plus size={14} aria-hidden />} onClick={() => { setAdding(true); setAddError(null) }} disabled={adding}>
              Add question
            </Button>
            <a href={evalSetCsvUrl(projectId, set.id)} download className={buttonClasses({ variant: 'secondary' })}>
              <Download size={14} aria-hidden /> Export CSV
            </a>
            <Button variant="secondary" icon={<Upload size={14} aria-hidden />} onClick={() => file.current?.click()} loading={importCsv.isPending}>
              Import CSV
            </Button>
            <input ref={file} type="file" accept=".csv,text/csv" className="hidden" aria-label="CSV file to import"
              onChange={(e) => void onFile(e.target.files?.[0])} />
            <span className="self-center text-body-sm text-text-tertiary">CSV columns: question, gold_answer, evidence, document (file name), facets (optional, | between facts), tests (optional, Python asserts)</span>
          </div>
          {adding && (
            <ItemForm
              initial={{ question: '', gold_answer: '', evidence: '', document_id: documents[0]?.value ?? '', facets: '', tests: '' }}
              documents={documents}
              saving={add.isPending}
              error={addError}
              onCancel={() => setAdding(false)}
              onSave={(d) =>
                add.mutate({ ...d, facets: splitFacets(d.facets), document_id: d.document_id || documents[0]?.value || '' }, {
                  onSuccess: () => setAdding(false),
                  onError: (e) => setAddError(errorMessage(e)),
                })
              }
            />
          )}
          <ul aria-label="Eval questions">
            {items.map((it) => <Row key={it.id} projectId={projectId} setId={set.id} item={it} />)}
          </ul>
        </div>
      </Dialog>
    </>
  )
}
