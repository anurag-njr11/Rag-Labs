import { useState, type FormEvent } from 'react'
import { errorMessage, useUpdateDocumentMetadata } from '@/api/hooks'
import { formatNumber } from '@/api/format'
import type { Document } from '@/api/types'
import { Button, Field, Input, Select, Switch, Textarea, useToast } from '@/components/ui'

const STATUSES = ['draft', 'published', 'deprecated']

/** Edit a document's OKF fields (FR-2.30). Saving never rebuilds the index. */
export function MetadataForm({ projectId, doc, onDone }: { projectId: string; doc: Document; onDone: () => void }) {
  const update = useUpdateDocumentMetadata(projectId)
  const { toast } = useToast()
  const o = doc.okf
  const [status, setStatus] = useState(o.status ?? '')
  const [staleAfter, setStaleAfter] = useState(o.stale_after ?? '')
  const [verified, setVerified] = useState(!!o.verified)
  const [verifiedOn, setVerifiedOn] = useState(typeof o.verified === 'string' ? o.verified : '')
  const [sources, setSources] = useState((o.sources ?? []).join('\n'))
  const statuses = status && !STATUSES.includes(status) ? [...STATUSES, status] : STATUSES

  const save = (e: FormEvent) => {
    e.preventDefault()
    const srcs = sources.split('\n').map((s) => s.trim()).filter(Boolean)
    update.mutate(
      {
        docId: doc.id,
        okf: {
          ...(status && { status }),
          ...(staleAfter && { stale_after: staleAfter }),
          ...(verified && { verified: verifiedOn || true }),
          ...(srcs.length > 0 && { sources: srcs }),
        },
      },
      {
        onSuccess: () => {
          toast({ tone: 'success', title: `Saved metadata for ${doc.filename}` })
          onDone()
        },
        onError: (err) => toast({ tone: 'danger', title: 'Could not save metadata', description: errorMessage(err) }),
      },
    )
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Status">
          {(f) => (
            <Select id={f.id} value={status} onChange={(e) => setStatus(e.target.value)}
              options={[{ value: '', label: 'Not set' }, ...statuses.map((s) => ({ value: s, label: s[0].toUpperCase() + s.slice(1) }))]} />
          )}
        </Field>
        <Field label="Stale after" help="Corpus Health flags it after this date.">
          {(f) => <Input id={f.id} aria-describedby={f.describedBy} type="date" value={staleAfter} onChange={(e) => setStaleAfter(e.target.value)} />}
        </Field>
      </div>
      <Field label="Verified" help="Turn on to mark it checked; the date is optional.">
        {(f) => (
          <div className="flex items-center gap-3">
            <Switch checked={verified} onChange={setVerified} aria-label="Verified" />
            <Input id={f.id} aria-describedby={f.describedBy} aria-label="Verified on" type="date" value={verifiedOn}
              disabled={!verified} onChange={(e) => setVerifiedOn(e.target.value)} wrapperClassName="flex-1" />
          </div>
        )}
      </Field>
      <Field label="Sources" help="One URL or reference per line.">
        {(f) => <Textarea id={f.id} aria-describedby={f.describedBy} rows={3} value={sources} onChange={(e) => setSources(e.target.value)} />}
      </Field>
      <p className="text-body-sm text-text-tertiary">
        Usage count: {formatNumber(o.usage_count)} — how often its passages appeared in Playground/API retrievals.
        {doc.last_modified && ` Last modified ${new Date(doc.last_modified).toLocaleDateString()}.`} Saving doesn’t rebuild the index.
      </p>
      <div className="flex justify-end gap-2">
        <Button type="button" onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" loading={update.isPending}>Save</Button>
      </div>
    </form>
  )
}
