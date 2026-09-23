import { useState } from 'react'
import { ArrowLeft, ArrowRight, FileText, Globe, Link as LinkIcon, Trash2, Upload } from 'lucide-react'
import { errorMessage, useDeleteDocument, useDocuments, useUploadDocuments } from '@/api/hooks'
import { fileTypeLabel, formatBytes, formatNumber } from '@/api/format'
import type { Document, Project } from '@/api/types'
import { JobProgress } from '@/app/JobProgress'
import { Badge, Button, Card, Spinner, Tabs, tabPanelProps, useToast } from '@/components/ui'
import { AddUrlForm } from '@/features/documents/AddUrlForm'
import { UploadDropzone } from '@/features/documents/UploadDropzone'
import { uploadSummary } from '@/features/documents/files'
import { StepIntro, WizardBody, WizardFooter } from './WizardShell'

type Source = 'files' | 'url'

/** Step 2 — upload files (`?build=false`, nothing is indexed yet) or import a URL / sitemap. */
export function DocumentsStep({ project, onBack, onNext }: { project: Project; onBack: () => void; onNext: () => void }) {
  const pid = project.id
  const { toast } = useToast()
  const [source, setSource] = useState<Source>('files')
  const [urlJobs, setUrlJobs] = useState<{ id: string; url: string }[]>([])
  const docsQ = useDocuments(pid, { refetchInterval: urlJobs.length ? 2500 : false })
  const upload = useUploadDocuments(pid)
  const docs = docsQ.data ?? []

  const onFiles = (files: File[]) =>
    upload.mutate(
      { files, build: false },
      {
        onSuccess: (r) => {
          const s = uploadSummary(r)
          toast({ tone: s.tone, title: s.title, description: s.description })
        },
        onError: (e) => toast({ tone: 'danger', title: 'Upload failed', description: errorMessage(e) }),
      },
    )

  const busy = upload.isPending || urlJobs.length > 0
  const hint = urlJobs.length
    ? 'Waiting for the URL import to finish…'
    : docs.length
      ? `Step 2 of 4 · ${formatNumber(docs.length)} document${docs.length === 1 ? '' : 's'} · ${formatBytes(docs.reduce((n, d) => n + d.size_bytes, 0))}`
      : 'Step 2 of 4 · add at least one document'

  return (
    <div className="flex flex-1 flex-col">
      <WizardBody>
        <StepIntro
          title="Add documents"
          description="Nothing is indexed yet — you’ll choose how to parse, chunk and embed them in the next step."
        />
        <Card padding="lg" className="flex flex-col gap-4">
          <Tabs<Source>
            aria-label="Document source"
            idPrefix="wiz-src"
            value={source}
            onChange={setSource}
            items={[
              { value: 'files', label: 'Upload files', icon: <Upload size={14} aria-hidden /> },
              { value: 'url', label: 'From URL', icon: <LinkIcon size={14} aria-hidden /> },
            ]}
            className="self-start"
          />
          <div {...tabPanelProps('wiz-src', source)}>
            {source === 'files' ? (
              <UploadDropzone onFiles={onFiles} uploading={upload.isPending} />
            ) : (
              <div className="flex flex-col gap-3">
                <AddUrlForm
                  projectId={pid}
                  layout="inline"
                  build={false}
                  onStarted={(id, url) => setUrlJobs((js) => [...js, { id, url }])}
                />
              </div>
            )}
          </div>
          {urlJobs.map((j) => (
            <div key={j.id} className="flex flex-col gap-2 rounded-lg border border-border-default px-3 py-2.5 sm:flex-row sm:items-center sm:gap-3">
              <span className="flex min-w-0 items-center gap-2 text-label sm:w-56">
                <Globe size={14} aria-hidden className="shrink-0 text-text-tertiary" />
                <span className="truncate">{j.url.replace(/^https?:\/\//, '')}</span>
              </span>
              <JobProgress
                variant="compact"
                showFetch
                jobId={j.id}
                projectId={pid}
                className="flex-1"
                onDone={(r) => {
                  setUrlJobs((js) => js.filter((x) => x.id !== j.id))
                  void docsQ.refetch()
                  const f = r.fetch
                  toast({
                    tone: f && f.created === 0 ? 'warning' : 'success',
                    title: f ? `Imported ${formatNumber(f.created)} page${f.created === 1 ? '' : 's'}` : 'Import finished',
                    description: f && (f.failed || f.duplicates) ? `${f.failed} failed · ${f.duplicates} duplicates` : undefined,
                  })
                }}
                onFailed={(err) => {
                  setUrlJobs((js) => js.filter((x) => x.id !== j.id))
                  toast({ tone: 'danger', title: 'URL import failed', description: err })
                }}
              />
            </div>
          ))}
        </Card>

        <section aria-labelledby="wiz-docs-h" className="flex flex-col gap-3">
          <h3 id="wiz-docs-h" className="flex items-center gap-2 text-heading">
            Documents <Badge tone="neutral">{formatNumber(docs.length)}</Badge>
          </h3>
          {docsQ.isPending ? (
            <div className="flex justify-center py-6 text-text-tertiary"><Spinner /></div>
          ) : docsQ.isError ? (
            <p role="alert" className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger-fg">
              {errorMessage(docsQ.error)} <Button size="sm" className="ml-2" onClick={() => void docsQ.refetch()}>Retry</Button>
            </p>
          ) : docs.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border-strong px-4 py-6 text-center text-body text-text-tertiary">
              No documents yet. Uploaded files appear here.
            </p>
          ) : (
            <Card padding="none" className="divide-y divide-border-default overflow-hidden">
              {docs.map((d) => <DocRow key={d.id} doc={d} projectId={pid} />)}
            </Card>
          )}
        </section>
      </WizardBody>
      <WizardFooter step={1} hint={hint}>
        <Button icon={<ArrowLeft size={14} aria-hidden />} onClick={onBack}>Back</Button>
        <Button
          variant="primary"
          iconRight={<ArrowRight size={14} aria-hidden />}
          disabled={docs.length === 0 || busy}
          onClick={onNext}
        >
          Continue
        </Button>
      </WizardFooter>
    </div>
  )
}

function DocRow({ doc, projectId }: { doc: Document; projectId: string }) {
  const del = useDeleteDocument(projectId)
  const { toast } = useToast()
  return (
    <div className="flex h-[52px] items-center gap-3 px-4 hover:bg-bg-subtle">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border-default bg-bg-subtle text-text-secondary">
        {doc.source_url ? <Globe size={14} aria-hidden /> : <FileText size={14} aria-hidden />}
      </span>
      <span className="min-w-0 flex-1 truncate font-mono text-mono" title={doc.source_url ?? doc.filename}>{doc.filename}</span>
      <span className="hidden w-20 text-body text-text-secondary sm:block">{fileTypeLabel(doc.filename)}</span>
      <span className="w-16 text-right font-mono text-mono text-text-secondary">{formatBytes(doc.size_bytes)}</span>
      {doc.status === 'failed' && <Badge tone="danger" dot title={doc.error ?? undefined}>Failed</Badge>}
      <Button
        variant="ghost"
        size="sm"
        iconOnly
        aria-label={`Remove ${doc.filename}`}
        loading={del.isPending}
        className="hover:text-danger-fg"
        icon={<Trash2 size={14} aria-hidden />}
        onClick={() =>
          del.mutate(doc.id, {
            onError: (e) => toast({ tone: 'danger', title: `Could not remove ${doc.filename}`, description: errorMessage(e) }),
          })
        }
      />
    </div>
  )
}
