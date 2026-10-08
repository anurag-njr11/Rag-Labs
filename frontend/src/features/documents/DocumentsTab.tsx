import { useMemo, useRef, useState, type DragEvent } from 'react'
import { Download, Ellipsis, FileText, Globe, Link as LinkIcon, PackageOpen, RefreshCw, Search, Tag, Trash2, TriangleAlert, Upload, X } from 'lucide-react'
import {
  errorMessage, useDeleteDocument, useDocuments, useImportOkf, useProjectJobs, useReindexDocument, useUploadDocuments,
} from '@/api/hooks'
import { API_BASE } from '@/api/client'
import { fileTypeLabel, formatBytes, formatNumber } from '@/api/format'
import type { Document } from '@/api/types'
import { useWorkspace } from '@/app/workspace'
import { JobProgress } from '@/app/JobProgress'
import {
  Badge, Button, Card, Dialog, EmptyState, Input, Popover, StatusBadge, Tooltip, cn, useToast,
} from '@/components/ui'
import { AddUrlForm } from './AddUrlForm'
import { ChunkViewer } from './ChunkViewer'
import { MetadataForm } from './MetadataForm'
import { ParseQualityBadge } from './ParseQualityCard'
import { UploadDropzone } from './UploadDropzone'
import { ACCEPT_ATTR, documentStatus, uploadSummary, validateFiles } from './files'

interface LocalJob {
  id: string
  label: string
  url?: boolean
}

// Columns (DESIGN §3 Table row/Document): file (fill) · type 80 · size 80 · modified 100 · status 100 · chunks 72 · parse 100 · actions 180
const CELL = 'px-2 first:pl-4 last:pr-4 align-middle'

export default function DocumentsTab() {
  const { project } = useWorkspace()
  const pid = project.id
  const { toast } = useToast()
  const jobsQ = useProjectJobs(pid)
  const [localJobs, setLocalJobs] = useState<LocalJob[]>([])
  const running = localJobs.length > 0 || (jobsQ.data?.length ?? 0) > 0 || !!project.index?.job_id
  const docsQ = useDocuments(pid, { refetchInterval: running ? 2500 : false })
  const upload = useUploadDocuments(pid)
  const importOkf = useImportOkf(pid)
  const bundleInput = useRef<HTMLInputElement>(null)
  const moreRef = useRef<HTMLButtonElement>(null)
  const [moreOpen, setMoreOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [urlOpen, setUrlOpen] = useState(false)
  const [viewing, setViewing] = useState<Document | null>(null)
  const [editing, setEditing] = useState<Document | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const addJob = (j: LocalJob) => setLocalJobs((js) => (js.some((x) => x.id === j.id) ? js : [...js, j]))
  const dropJob = (id: string) => setLocalJobs((js) => js.filter((j) => j.id !== id))

  const jobs = useMemo(() => {
    const list: LocalJob[] = [...localJobs]
    for (const j of jobsQ.data ?? []) if (!list.some((x) => x.id === j.id)) list.push({ id: j.id, label: 'Index update' })
    return list
  }, [localJobs, jobsQ.data])

  const doImportOkf = (file: File | undefined) => {
    if (!file) return
    importOkf.mutate(file, {
      onSuccess: (r) => {
        const parts = [
          r.duplicates.length && `${r.duplicates.length} already here`,
          r.skipped.length && `${r.skipped.length} non-Markdown file${r.skipped.length === 1 ? '' : 's'} skipped`,
          r.errors.length && `${r.errors.length} failed: ${r.errors.map((e) => `${e.path} (${e.error})`).join(', ')}`,
        ].filter(Boolean)
        toast({
          tone: r.errors.length ? 'warning' : 'success',
          title: `Imported ${r.created.length} document${r.created.length === 1 ? '' : 's'} from the bundle`,
          description: parts.join(' · ') || 'Their OKF metadata (type, status, verified, sources, stale_after) came along.',
        })
        if (r.job_id) addJob({ id: r.job_id, label: `Indexing ${r.created.length} imported document${r.created.length === 1 ? '' : 's'}` })
      },
      onError: (e) => toast({ tone: 'danger', title: 'Bundle import failed', description: errorMessage(e) }),
    })
  }

  const doUpload = (files: File[]) => {
    upload.mutate(
      { files },
      {
        onSuccess: (r) => {
          const s = uploadSummary(r)
          toast({ tone: s.tone, title: s.title, description: s.description })
          if (r.job_id) addJob({ id: r.job_id, label: `Indexing ${r.created.length} new file${r.created.length === 1 ? '' : 's'}` })
        },
        onError: (e) => toast({ tone: 'danger', title: 'Upload failed', description: errorMessage(e) }),
      },
    )
  }

  const pick = (list: FileList | null) => {
    if (!list?.length) return
    const { accepted, rejected } = validateFiles(Array.from(list))
    if (rejected.length) {
      toast({
        tone: 'warning',
        title: `${rejected.length} file${rejected.length === 1 ? '' : 's'} skipped`,
        description: rejected.map((r) => `${r.name}: ${r.reason}`).join(' · '),
      })
    }
    if (accepted.length) doUpload(accepted)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    pick(e.dataTransfer.files)
  }

  const docs = docsQ.data ?? []
  const filtered = query ? docs.filter((d) => d.filename.toLowerCase().includes(query.toLowerCase())) : docs
  const totalChunks = docs.reduce((n, d) => n + (d.chunks ?? 0), 0)
  const totalBytes = docs.reduce((n, d) => n + d.size_bytes, 0)

  return (
    <div
      className="relative mx-auto flex w-full max-w-[1440px] flex-col gap-4 px-4 py-8 sm:px-8"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) {
          e.preventDefault()
          setDragging(true)
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false)
      }}
      onDrop={onDrop}
    >
      <input
        ref={fileInput}
        type="file"
        multiple
        accept={ACCEPT_ATTR}
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          pick(e.target.files)
          e.target.value = ''
        }}
      />

      {/* Header row */}
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-label text-text-primary">
          {docsQ.isPending
            ? 'Loading documents…'
            : `${formatNumber(docs.length)} document${docs.length === 1 ? '' : 's'} · ${formatNumber(totalChunks)} chunks · ${formatBytes(totalBytes)}`}
        </p>
        <Input
          icon={<Search />}
          placeholder="Search documents"
          aria-label="Search documents"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          wrapperClassName="w-full sm:w-60"
        />
        <div className="flex w-full gap-2 sm:ml-auto sm:w-auto">
          <Button icon={<LinkIcon size={14} aria-hidden />} onClick={() => setUrlOpen(true)} className="flex-1 sm:flex-none">
            Add URL
          </Button>
          <Button ref={moreRef} iconOnly aria-label="Import or export a metadata bundle" aria-haspopup="menu" aria-expanded={moreOpen}
            loading={importOkf.isPending} icon={<Ellipsis size={16} aria-hidden />} onClick={() => setMoreOpen((o) => !o)} />
          <Popover open={moreOpen} onClose={() => setMoreOpen(false)} anchor={moreRef} width={260} className="p-1" aria-label="Metadata bundle">
            <button type="button" onClick={() => { setMoreOpen(false); bundleInput.current?.click() }}
              title="An Open Knowledge Format bundle: a .zip of Markdown files with YAML front matter"
              className="focus-ring flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-label hover:bg-bg-subtle">
              <PackageOpen size={14} aria-hidden /> Import metadata bundle (OKF)
            </button>
            <a href={`${API_BASE}/projects/${pid}/documents/okf-export`} download onClick={() => setMoreOpen(false)}
              title="Download the corpus as an OKF bundle: text, provenance, trust tier, status, usage and Corpus Health findings"
              className="focus-ring flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-label hover:bg-bg-subtle">
              <Download size={14} aria-hidden /> Export metadata bundle (OKF)
            </a>
          </Popover>
          <input ref={bundleInput} type="file" accept=".zip,application/zip" hidden aria-hidden tabIndex={-1}
            onChange={(e) => { doImportOkf(e.target.files?.[0]); e.target.value = '' }} />
          <Button
            variant="primary"
            icon={<Upload size={14} aria-hidden />}
            loading={upload.isPending}
            onClick={() => fileInput.current?.click()}
            className="flex-1 sm:flex-none"
          >
            Upload files
          </Button>
        </div>
      </div>

      {/* Running jobs */}
      {jobs.length > 0 && (
        <Card padding="none" className="divide-y divide-border-default" aria-label="Running jobs">
          {jobs.map((j) => (
            <div key={j.id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
              <span className="flex min-w-0 items-center gap-2 text-label sm:w-56">
                {j.url ? <Globe size={14} aria-hidden className="shrink-0 text-text-tertiary" /> : <RefreshCw size={14} aria-hidden className="shrink-0 text-text-tertiary" />}
                <span className="truncate">{j.label}</span>
              </span>
              <JobProgress
                variant="compact"
                jobId={j.id}
                projectId={pid}
                showFetch={j.url}
                className="flex-1"
                onDone={(r) => {
                  dropJob(j.id)
                  void jobsQ.refetch()
                  const f = r.fetch
                  toast({
                    tone: 'success',
                    title: f ? `Imported ${formatNumber(f.created)} page${f.created === 1 ? '' : 's'}` : 'Index updated',
                    description: `${f && f.failed ? `${f.failed} failed · ` : ''}${f && f.duplicates ? `${f.duplicates} duplicates · ` : ''}${r.build ? `${formatNumber(r.build.chunk_count)} chunks in the index.` : 'Not indexed yet.'}`,
                  })
                }}
                onFailed={(err) => {
                  dropJob(j.id)
                  void jobsQ.refetch()
                  toast({ tone: 'danger', title: `${j.label} failed`, description: err })
                }}
              />
            </div>
          ))}
        </Card>
      )}

      {/* Table / states */}
      {docsQ.isPending ? (
        <Card padding="none" className="overflow-hidden">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex h-[52px] items-center gap-3 border-b border-border-default px-4 last:border-0">
              <div className="h-3 w-48 animate-pulse rounded bg-bg-muted" />
              <div className="ml-auto h-3 w-24 animate-pulse rounded bg-bg-muted" />
            </div>
          ))}
        </Card>
      ) : docsQ.isError ? (
        <EmptyState
          icon={<TriangleAlert aria-hidden />}
          title="Could not load documents"
          description={errorMessage(docsQ.error)}
          actions={<Button onClick={() => void docsQ.refetch()}>Retry</Button>}
        />
      ) : docs.length === 0 ? (
        <Card padding="lg" className="flex flex-col gap-4">
          <div>
            <h2 className="text-heading">Add your first documents</h2>
            <p className="mt-0.5 text-body text-text-secondary">They’re parsed, chunked and indexed with the active version’s settings.</p>
          </div>
          <UploadDropzone onFiles={doUpload} uploading={upload.isPending} />
          <div className="flex items-center gap-2 text-body-sm text-text-tertiary">
            or
            <Button size="sm" variant="ghost" icon={<LinkIcon size={12} aria-hidden />} onClick={() => setUrlOpen(true)}>
              import from a URL or sitemap
            </Button>
          </div>
        </Card>
      ) : (
        <Card padding="none" className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] table-fixed border-collapse text-left">
              <caption className="sr-only">Documents in {project.name}</caption>
              <thead>
                <tr className="h-9 border-b border-border-default bg-bg-subtle text-caption text-text-tertiary">
                  <th scope="col" className={cn(CELL, 'font-medium')}>File</th>
                  <th scope="col" className={cn(CELL, 'w-20 font-medium')}>Type</th>
                  <th scope="col" className={cn(CELL, 'w-20 text-right font-medium')}>Size</th>
                  <th scope="col" className={cn(CELL, 'w-[100px] font-medium')}>Status</th>
                  <th scope="col" className={cn(CELL, 'w-[72px] text-right font-medium')}>Chunks</th>
                  <th scope="col" className={cn(CELL, 'w-[100px] font-medium')}>Parse</th>
                  <th scope="col" className={cn(CELL, 'w-[180px] text-right font-medium')}><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((d) => (
                  <DocumentRow
                    key={d.id}
                    doc={d}
                    projectId={pid}
                    building={running}
                    onView={() => setViewing(d)}
                    onEdit={() => setEditing(d)}
                    onJob={(id) => addJob({ id, label: `Re-indexing ${d.filename}` })}
                  />
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-text-tertiary">
                      No documents match “{query}”.
                      <Button size="sm" variant="ghost" className="ml-2" icon={<X size={12} aria-hidden />} onClick={() => setQuery('')}>Clear</Button>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {dragging && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-2 z-20 flex items-center justify-center rounded-xl border-2 border-dashed border-accent-default bg-accent-subtle/80"
        >
          <span className="flex items-center gap-2 text-heading text-accent-text"><Upload size={18} /> Drop files to upload</span>
        </div>
      )}

      <Dialog open={urlOpen} onClose={() => setUrlOpen(false)} title="Add from URL" description="Fetch a web page or a whole sitemap. Pages are indexed as soon as they’re fetched.">
        <AddUrlForm
          projectId={pid}
          onCancel={() => setUrlOpen(false)}
          onStarted={(id, url) => {
            setUrlOpen(false)
            addJob({ id, label: `Importing ${url.replace(/^https?:\/\//, '')}`, url: true })
          }}
        />
      </Dialog>

      <Dialog open={!!editing} onClose={() => setEditing(null)} title="Document metadata"
        description={editing ? `${editing.filename} · optional OKF fields. Corpus Health flags deprecated and stale documents.` : undefined}>
        {editing && <MetadataForm key={editing.id} projectId={pid} doc={editing} onDone={() => setEditing(null)} />}
      </Dialog>

      <ChunkViewer projectId={pid} doc={viewing} onClose={() => setViewing(null)} />
    </div>
  )
}

const STATUS_TONE: Record<string, 'danger' | 'warning' | 'success'> = { deprecated: 'danger', draft: 'warning', published: 'success' }

function DocumentRow({
  doc, projectId, building, onView, onEdit, onJob,
}: { doc: Document; projectId: string; building: boolean; onView: () => void; onEdit: () => void; onJob: (jobId: string) => void }) {
  const { toast } = useToast()
  const del = useDeleteDocument(projectId)
  const reindex = useReindexDocument(projectId)
  const [confirm, setConfirm] = useState(false)
  const [menu, setMenu] = useState(false)
  const trash = useRef<HTMLButtonElement>(null)
  const st = documentStatus(doc, building)

  const doDelete = () => {
    setConfirm(false)
    del.mutate(doc.id, {
      onSuccess: () => toast({ tone: 'success', title: `Deleted ${doc.filename}` }),
      onError: (e) => toast({ tone: 'danger', title: `Could not delete ${doc.filename}`, description: errorMessage(e) }),
    })
  }
  const doReindex = () =>
    reindex.mutate(doc.id, {
      onSuccess: (r) => onJob(r.job_id),
      onError: (e) => toast({ tone: 'danger', title: `Could not re-index ${doc.filename}`, description: errorMessage(e) }),
    })

  return (
    <tr className="h-[52px] border-b border-border-default last:border-0 hover:bg-bg-subtle">
      <td className={cn(CELL, 'min-w-0')}>
        <button
          type="button"
          onClick={onView}
          title={doc.source_url ?? doc.filename}
          className="focus-ring flex max-w-full items-center gap-2.5 rounded-sm text-left"
        >
          <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border-default bg-bg-subtle text-text-secondary">
            {doc.source_url ? <Globe size={14} aria-hidden /> : <FileText size={14} aria-hidden />}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-mono text-mono text-text-primary hover:underline">{doc.filename}</span>
            {doc.source_url && <span className="block truncate text-body-sm text-text-tertiary">{doc.source_url}</span>}
          </span>
          {doc.okf.type && <Badge tone="neutral" className="shrink-0">{doc.okf.type}</Badge>}
          {doc.okf.status && <Badge tone={STATUS_TONE[doc.okf.status.toLowerCase()] ?? 'neutral'} className="shrink-0">{doc.okf.status}</Badge>}
          {typeof doc.okf.verified === 'string' && /^(human|process|agent):/i.test(doc.okf.verified) && (
            <Badge tone={doc.okf.verified.toLowerCase().startsWith('human') ? 'success' : 'info'} className="shrink-0" title={`verified: ${doc.okf.verified}`}>
              {doc.okf.verified.split(':')[0].toLowerCase()}-verified
            </Badge>
          )}
        </button>
      </td>
      <td className={cn(CELL, 'text-body text-text-secondary')}>{fileTypeLabel(doc.filename)}</td>
      <td className={cn(CELL, 'text-right font-mono text-mono text-text-secondary')}>{formatBytes(doc.size_bytes)}</td>
      <td className={CELL}>
        {st.error ? (
          <Tooltip content={st.error}>
            <span tabIndex={0} className="focus-ring inline-flex rounded-sm" aria-label={`Failed: ${st.error}`}>
              <StatusBadge status={st.status} withIcon />
            </span>
          </Tooltip>
        ) : (
          <StatusBadge status={st.status} withIcon />
        )}
      </td>
      <td className={cn(CELL, 'text-right font-mono text-mono text-text-primary')}>{doc.chunks == null ? '—' : formatNumber(doc.chunks)}</td>
      <td className={CELL}>
        <div className="flex items-center">
          <ParseQualityBadge doc={doc} onViewChunks={onView} />
        </div>
      </td>
      <td className={CELL}>
        <div className="flex items-center justify-end gap-1">
        <Button
          ref={trash}
          variant="ghost"
          size="sm"
          iconOnly
          aria-label={`Actions for ${doc.filename}`}
          aria-haspopup="menu"
          aria-expanded={menu}
          loading={reindex.isPending || del.isPending}
          onClick={() => setMenu((m) => !m)}
          icon={<Ellipsis size={14} aria-hidden />}
        />
        <Popover open={menu} onClose={() => setMenu(false)} anchor={trash} width={190} className="p-1" aria-label={`Actions for ${doc.filename}`}>
          {[
            { label: 'Re-index', icon: <RefreshCw size={14} aria-hidden />, run: doReindex, danger: false },
            { label: 'Edit metadata', icon: <Tag size={14} aria-hidden />, run: onEdit, danger: false },
            { label: 'Delete…', icon: <Trash2 size={14} aria-hidden />, run: () => setConfirm(true), danger: true },
          ].map((a) => (
            <button key={a.label} type="button" onClick={() => { setMenu(false); a.run() }}
              className={cn('focus-ring flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-label', a.danger ? 'text-danger-fg hover:bg-danger-bg' : 'hover:bg-bg-subtle')}>
              {a.icon} {a.label}
            </button>
          ))}
        </Popover>
        <Popover open={confirm} onClose={() => setConfirm(false)} anchor={trash} aria-label={`Delete ${doc.filename}`}>
          <p className="text-body text-text-primary">
            Delete <span className="font-mono text-mono">{doc.filename}</span>
            {doc.chunks ? ` and its ${formatNumber(doc.chunks)} chunks` : ''}?
          </p>
          <p className="mt-1 text-body-sm text-text-tertiary">It’s removed from every index. This can’t be undone.</p>
          <div className="mt-3 flex justify-end gap-2">
            <Button size="sm" onClick={() => setConfirm(false)}>Cancel</Button>
            <Button size="sm" variant="danger" onClick={doDelete} icon={<Trash2 size={12} aria-hidden />}>Delete</Button>
          </div>
        </Popover>
        </div>
      </td>
    </tr>
  )
}

