import { Suspense, useLayoutEffect, useRef, useState } from 'react'
import { Link, Outlet, useLocation, useParams } from 'react-router-dom'
import { ChevronRight, Database, FolderX, GitCommitHorizontal, RefreshCw } from 'lucide-react'
import { ApiError, errorMessage, useBuildVersion, useProject } from '@/api/hooks'
import { formatNumber, storeLabel } from '@/api/format'
import type { IndexStatus, Project } from '@/api/types'
import { Button, ButtonLink, EmptyState, Pill, TabLinks, useToast } from '@/components/ui'
import { PageFallback } from './AppLayout'
import { JobProgress } from './JobProgress'
import { ProviderKeyBanner } from './ProviderKeyBanner'
import type { WorkspaceContext } from './workspace'

const INDEX_DOT: Record<IndexStatus['status'], string> = {
  ready: 'bg-success-fg',
  building: 'bg-info-fg',
  pending: 'bg-neutral-fg',
  not_built: 'bg-neutral-fg',
  stale: 'bg-warning-fg',
  failed: 'bg-danger-fg',
}
const INDEX_LABEL: Record<IndexStatus['status'], string> = {
  ready: 'Index ready',
  building: 'Index building',
  pending: 'Index pending',
  not_built: 'Index not built',
  stale: 'Index stale',
  failed: 'Index failed',
}

function indexPillText(p: Project): string {
  const ix = p.index
  if (!ix) return p.documents === 0 ? 'No documents' : 'Index not built'
  const parts = [INDEX_LABEL[ix.status] ?? ix.status]
  if (ix.chunk_count) parts.push(`${formatNumber(ix.chunk_count)} chunks`)
  if (ix.store) parts.push(storeLabel(ix.store))
  return parts.join(' · ')
}

function WorkspaceHeader({ project }: { project: Project }) {
  const build = useBuildVersion(project.id)
  const { toast } = useToast()
  const [jobId, setJobId] = useState<string | null>(null)
  const runningJob = project.index?.job_id ?? jobId
  const busy = !!project.index?.job_id || project.index?.status === 'building' || project.index?.status === 'pending'
  // The Documents tab shows its own running-jobs card; don't show the same build twice.
  const onDocumentsTab = useLocation().pathname.endsWith('/documents')

  const rebuild = () => {
    if (!project.active_version_id) return
    build.mutate(project.active_version_id, {
      onSuccess: (r) => setJobId(r.job_id),
      onError: (e) => toast({ tone: 'danger', title: 'Could not start the build', description: errorMessage(e) }),
    })
  }

  const base = `/projects/${project.id}`
  return (
    <div className="border-b border-border-default bg-bg-surface px-4 pt-4 sm:px-8">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-body-sm">
        <Link to="/" className="focus-ring rounded-sm text-text-tertiary hover:text-text-primary">Projects</Link>
        <ChevronRight size={12} aria-hidden className="text-text-tertiary" />
        <span aria-current="page" className="truncate text-text-secondary">{project.name}</span>
      </nav>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="min-w-0 truncate text-display text-text-primary">{project.name}</h1>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {project.active_version && (
            <Pill icon={<GitCommitHorizontal aria-hidden />}>v{project.active_version.version} · active</Pill>
          )}
          <Pill icon={<Database aria-hidden />} dotClassName={project.index ? INDEX_DOT[project.index.status] : 'bg-neutral-fg'}>
            {indexPillText(project)}
          </Pill>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button
            icon={<RefreshCw size={14} aria-hidden className={busy ? 'animate-spin' : undefined} />}
            onClick={rebuild}
            loading={build.isPending}
            disabled={busy || !project.active_version_id || project.documents === 0}
            title={project.documents === 0 ? 'Add documents first' : undefined}
          >
            {busy ? 'Building…' : 'Rebuild index'}
          </Button>
        </div>
      </div>

      {runningJob && (jobId || (busy && !onDocumentsTab)) && (
        <JobProgress
          variant="compact"
          jobId={runningJob}
          projectId={project.id}
          className="mt-3"
          onDone={(r) => {
            setJobId(null)
            toast({ tone: 'success', title: 'Index ready', description: `${formatNumber(r.build?.chunk_count ?? 0)} chunks indexed.` })
          }}
          onFailed={(err) => {
            setJobId(null)
            toast({ tone: 'danger', title: 'Index build failed', description: err })
          }}
        />
      )}
      {project.index?.status === 'failed' && project.index.error && !busy && (
        <p role="alert" className="mt-2 text-body-sm text-danger-fg">Last build failed: {project.index.error}</p>
      )}

      <TabLinks
        aria-label="Project sections"
        className="mt-3"
        items={[
          { to: `${base}/documents`, label: 'Documents' },
          { to: `${base}/configure`, label: 'Configure' },
          { to: `${base}/versions`, label: 'Versions' },
          { to: `${base}/playground`, label: 'Playground' },
          { to: `${base}/api`, label: 'API' },
        ]}
      />
    </div>
  )
}

/**
 * Workspace shell for /projects/:id/* — provider-key banner, project header (breadcrumb, pills, rebuild, tabs),
 * then the tab via <Outlet context={{project}} />. Sets CSS var `--chrome-h` (top bar + banner + header height)
 * so full-height tabs can use `h-[calc(100dvh-var(--chrome-h))]`.
 */
export function WorkspaceLayout() {
  const { id = '' } = useParams<{ id: string }>()
  const q = useProject(id)
  const chrome = useRef<HTMLDivElement>(null)
  const [chromeH, setChromeH] = useState(0)

  useLayoutEffect(() => {
    const el = chrome.current
    if (!el) return
    const ro = new ResizeObserver(() => setChromeH(el.offsetHeight))
    ro.observe(el)
    setChromeH(el.offsetHeight)
    return () => ro.disconnect()
  }, [q.data?.id])

  if (q.isPending) return <PageFallback />
  if (q.isError || !q.data) {
    const notFound = q.error instanceof ApiError && q.error.status === 404
    return (
      <div className="px-4 py-12 sm:px-8">
        <EmptyState
          icon={<FolderX aria-hidden />}
          title={notFound ? 'Project not found' : 'Could not load the project'}
          description={notFound ? 'It may have been deleted.' : errorMessage(q.error)}
          actions={
            <>
              {!notFound && <Button onClick={() => void q.refetch()}>Retry</Button>}
              <ButtonLink to="/" variant="primary">All projects</ButtonLink>
            </>
          }
        />
      </div>
    )
  }

  const ctx: WorkspaceContext = { project: q.data }
  return (
    <div className="flex min-h-0 flex-1 flex-col" style={{ ['--chrome-h' as string]: `calc(var(--topbar-h) + ${chromeH}px)` }}>
      <div ref={chrome}>
        <ProviderKeyBanner />
        <WorkspaceHeader project={q.data} />
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        <Suspense fallback={<PageFallback />}>
          <Outlet context={ctx} />
        </Suspense>
      </div>
    </div>
  )
}
