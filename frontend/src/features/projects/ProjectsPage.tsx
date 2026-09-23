import { useState, type ReactNode } from 'react'
import { FolderOpen, Plus, Search, SlidersHorizontal, TriangleAlert, Upload, MessageCircle } from 'lucide-react'
import { errorMessage, useDeleteProject, useProjects, useProviders } from '@/api/hooks'
import { formatNumber } from '@/api/format'
import type { Project } from '@/api/types'
import { Button, ButtonLink, Dialog, EmptyState, Input, useToast } from '@/components/ui'
import { ProjectCard } from './ProjectCard'

const GRID = 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4'

export default function ProjectsPage() {
  const q = useProjects()
  const providers = useProviders()
  const [query, setQuery] = useState('')
  const [toDelete, setToDelete] = useState<Project | null>(null)

  const all = q.data ?? []
  const list = query
    ? all.filter((p) => `${p.name} ${p.description}`.toLowerCase().includes(query.toLowerCase()))
    : all
  const newButton = (
    <ButtonLink to="/new" variant="primary" icon={<Plus size={14} aria-hidden />}>
      New project
    </ButtonLink>
  )

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 py-8 sm:px-12">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display text-text-primary">Projects</h1>
          <p className="mt-1 text-body text-text-secondary">
            {q.data && all.length > 0
              ? `${formatNumber(all.length)} project${all.length === 1 ? '' : 's'} · each is a document set with versioned retrieval pipelines`
              : 'Each project is a document set with versioned retrieval pipelines.'}
          </p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          {all.length > 3 && (
            <Input
              icon={<Search />}
              placeholder="Search projects"
              aria-label="Search projects"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              wrapperClassName="flex-1 sm:w-60 sm:flex-none"
            />
          )}
          {all.length > 0 && newButton}
        </div>
      </div>

      {q.isPending ? (
        <div className={GRID} aria-busy="true" aria-label="Loading projects">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-[228px] animate-pulse rounded-lg border border-border-default bg-bg-surface p-5">
              <div className="h-4 w-2/3 rounded bg-bg-muted" />
              <div className="mt-4 h-3 w-full rounded bg-bg-muted" />
              <div className="mt-2 h-3 w-1/2 rounded bg-bg-muted" />
            </div>
          ))}
        </div>
      ) : q.isError ? (
        <EmptyState
          icon={<TriangleAlert aria-hidden />}
          title="Could not load projects"
          description={errorMessage(q.error)}
          actions={<Button onClick={() => void q.refetch()}>Retry</Button>}
        />
      ) : all.length === 0 ? (
        <EmptyProjects action={newButton} />
      ) : (
        <>
          <ul className={GRID}>
            {list.map((p) => (
              <li key={p.id}>
                <ProjectCard project={p} providers={providers.data} onDelete={() => setToDelete(p)} />
              </li>
            ))}
          </ul>
          {list.length === 0 && (
            <p className="py-12 text-center text-body text-text-tertiary">No projects match “{query}”.</p>
          )}
        </>
      )}

      <DeleteProjectDialog project={toDelete} onClose={() => setToDelete(null)} />
    </div>
  )
}

function EmptyProjects({ action }: { action: ReactNode }) {
  const steps = [
    { icon: <Upload aria-hidden />, title: 'Add documents', text: 'Upload PDFs, Markdown, HTML or DOCX, or import a sitemap.' },
    { icon: <SlidersHorizontal aria-hidden />, title: 'Configure the pipeline', text: 'Pick parsing, chunking, embeddings, store, retrieval and model.' },
    { icon: <MessageCircle aria-hidden />, title: 'Ask questions', text: 'Answers cite their sources; inspect every retrieval step.' },
  ]
  return (
    <div className="mx-auto flex max-w-3xl flex-col items-center gap-8 rounded-xl border border-dashed border-border-strong bg-bg-surface px-6 py-14 text-center">
      <div className="flex flex-col items-center gap-3">
        <span className="flex size-12 items-center justify-center rounded-xl bg-bg-subtle text-text-secondary">
          <FolderOpen size={22} aria-hidden />
        </span>
        <h2 className="text-title text-text-primary">No projects yet</h2>
        <p className="max-w-md text-body text-text-secondary">
          Create a project to build your first retrieval pipeline. Start with the recommended settings — you can change everything later.
        </p>
        <div className="mt-1">{action}</div>
      </div>
      <ol className="grid w-full gap-3 text-left sm:grid-cols-3">
        {steps.map((s, i) => (
          <li key={s.title} className="rounded-lg border border-border-default bg-bg-subtle p-4">
            <div className="flex items-center gap-2 text-text-secondary [&_svg]:size-4">
              <span className="font-mono text-mono-sm text-text-tertiary">{i + 1}</span>
              {s.icon}
              <span className="text-label text-text-primary">{s.title}</span>
            </div>
            <p className="mt-1.5 text-body-sm text-text-secondary">{s.text}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}

function DeleteProjectDialog({ project, onClose }: { project: Project | null; onClose: () => void }) {
  const del = useDeleteProject()
  const { toast } = useToast()
  const p = project
  const close = () => {
    del.reset()
    onClose()
  }
  return (
    <Dialog
      open={!!p}
      onClose={() => !del.isPending && close()}
      size="sm"
      title="Delete project?"
      description={
        p ? (
          <>
            <strong className="font-semibold text-text-primary">{p.name}</strong> will be deleted with its {formatNumber(p.documents)} document
            {p.documents === 1 ? '' : 's'}, {formatNumber(p.versions)} version{p.versions === 1 ? '' : 's'} and every index. This can’t be undone.
          </>
        ) : undefined
      }
      footer={
        <>
          <Button onClick={close} disabled={del.isPending}>Cancel</Button>
          <Button
            variant="danger"
            loading={del.isPending}
            onClick={() =>
              p &&
              del.mutate(p.id, {
                onSuccess: () => {
                  toast({ tone: 'success', title: `Deleted ${p.name}` })
                  close()
                },
              })
            }
          >
            Delete project
          </Button>
        </>
      }
    >
      {del.isError && (
        <p role="alert" className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-danger-fg">{errorMessage(del.error)}</p>
      )}
    </Dialog>
  )
}
