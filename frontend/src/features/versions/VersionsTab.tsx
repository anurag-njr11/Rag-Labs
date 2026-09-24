import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CircleCheck, Download, GitCommitHorizontal, Play } from 'lucide-react'
import { API_BASE, errorMessage } from '@/api/client'
import { formatDateTime, formatNumber, formatRelative, shortHash, storeLabel } from '@/api/format'
import {
  useActivateVersion, useBuildVersion, useEstimate, useNodes, useVersion, useVersionDiff, useVersions,
} from '@/api/hooks'
import type { Change, EstimateResult, Version } from '@/api/types'
import { JobProgress } from '@/app/JobProgress'
import { useWorkspace } from '@/app/workspace'
import {
  Badge, Banner, Button, Card, CodeBlock, Dialog, Disclosure, EmptyState, Select, Spinner, StatusBadge, buttonClasses, cn, useToast,
} from '@/components/ui'
import { DiffTable } from './DiffTable'

export default function VersionsTab() {
  const { project } = useWorkspace()
  const versions = useVersions(project.id)
  const [params, setParams] = useSearchParams()
  const list = versions.data ?? []
  const selectedId = params.get('v') ?? project.active_version_id ?? list[0]?.id
  const selected = list.find((v) => v.id === selectedId) ?? list[0]

  const select = (id: string) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        n.set('v', id)
        return n
      },
      { replace: true },
    )

  if (versions.isLoading) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-text-secondary sm:px-8">
        <Spinner /> Loading versions…
      </div>
    )
  }
  if (versions.isError) {
    return (
      <div className="px-4 py-6 sm:px-8">
        <Banner tone="danger" title="Couldn't load versions">{errorMessage(versions.error)}</Banner>
      </div>
    )
  }
  if (!list.length || !selected) {
    return (
      <div className="px-4 py-6 sm:px-8">
        <EmptyState icon={<GitCommitHorizontal />} title="No versions yet" description="Save a configuration on the Configure tab to create one." />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6 px-4 py-6 sm:px-8 lg:flex-row lg:items-start">
      <Card padding="none" className="w-full shrink-0 overflow-hidden lg:sticky lg:top-[calc(var(--topbar-h)+16px)] lg:w-80">
        <div className="flex items-center justify-between border-b border-border-default px-4 py-3">
          <h2 className="text-heading text-text-primary">History</h2>
          <span className="text-body-sm text-text-tertiary">
            {list.length} version{list.length === 1 ? '' : 's'}
          </span>
        </div>
        <ul aria-label="Versions" className="max-h-[70vh] overflow-y-auto">
          {list.map((v) => (
            <li key={v.id} className="border-b border-border-default last:border-b-0">
              <VersionRow v={v} selected={v.id === selected.id} onSelect={() => select(v.id)} />
            </li>
          ))}
        </ul>
      </Card>
      <VersionDetail key={selected.id} version={selected} all={list} />
    </div>
  )
}

function VersionRow({ v, selected, onSelect }: { v: Version; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
      className={cn(
        'focus-ring relative flex min-h-16 w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors',
        selected ? 'bg-accent-subtle' : 'hover:bg-bg-subtle',
      )}
    >
      {selected && <span aria-hidden className="absolute inset-y-0 left-0 w-0.5 bg-accent-default" />}
      <span className="flex w-full items-center gap-2">
        <span className="font-mono text-mono font-medium text-text-primary">v{v.version}</span>
        <span className="min-w-0 flex-1 truncate text-label text-text-primary">{v.note || <span className="text-text-tertiary">No note</span>}</span>
        {v.active && <Badge tone="accent">active</Badge>}
      </span>
      <span className="flex w-full items-center gap-2 text-body-sm text-text-tertiary">
        <span title={formatDateTime(v.created_at)}>{formatRelative(v.created_at)}</span>
        <span aria-hidden>·</span>
        <span className="font-mono text-mono-sm" title={`Index config hash ${v.index_config_hash}`}>
          idx {shortHash(v.index_config_hash)}
        </span>
        <span className="flex-1" />
        {v.index && <StatusBadge status={v.index.status} />}
      </span>
    </button>
  )
}

function VersionDetail({ version, all }: { version: Version; all: Version[] }) {
  const { project } = useWorkspace()
  const { toast } = useToast()
  const detail = useVersion(project.id, version.id)
  const nodes = useNodes()
  const v = detail.data ?? version
  const activeV = all.find((x) => x.active)

  // Compare target: '' = parent (changes_from_parent), else another version id.
  // A first version has no parent: compare it with the active version instead.
  const [compareTo, setCompareTo] = useState(() => (!version.parent_id && !version.active && activeV ? activeV.id : ''))
  const diff = useVersionDiff(project.id, compareTo || undefined, compareTo ? v.id : undefined)

  // For a non-active version: what activating it would cost (estimate vs the active version).
  const estimateM = useEstimate(project.id)
  const [estimate, setEstimate] = useState<EstimateResult | null>(null)
  const estimateMutate = estimateM.mutate
  const cfgKey = JSON.stringify(version.config)
  const activeKey = project.active_version_id
  useEffect(() => {
    if (version.active) return
    estimateMutate(JSON.parse(cfgKey) as Version['config'], { onSuccess: setEstimate })
  }, [cfgKey, version.active, activeKey, estimateMutate])

  const activate = useActivateVersion(project.id)
  const build = useBuildVersion(project.id)
  const [confirm, setConfirm] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)

  const parentV = v.parent_version ?? all.find((x) => x.id === v.parent_id)?.version ?? null
  const changes: Change[] | undefined = compareTo ? diff.data?.changes : v.changes_from_parent
  const compareLabel = compareTo ? `v${all.find((x) => x.id === compareTo)?.version ?? '?'}` : parentV != null ? `v${parentV}` : null
  const loadingChanges = compareTo ? diff.isLoading : detail.isLoading

  const compareOptions = useMemo(
    () => [
      { value: '', label: parentV != null ? `Parent (v${parentV})` : 'Parent (none)' },
      ...all.filter((x) => x.id !== v.id).map((x) => ({ value: x.id, label: `v${x.version}${x.active ? ' · active' : ''}${x.note ? ` — ${x.note}` : ''}` })),
    ],
    [all, v.id, parentV],
  )

  const onError = (title: string) => (e: unknown) =>
    toast({ title, description: errorMessage(e), tone: 'danger' })

  const doActivate = () =>
    activate.mutate(v.id, {
      onSuccess: (r) => {
        setConfirm(false)
        toast({ title: `v${v.version} is now active`, description: r.job_id ? 'Updating the index…' : undefined, tone: 'success' })
        if (r.job_id) setJobId(r.job_id)
      },
      onError: (e) => {
        setConfirm(false)
        onError("Couldn't activate")(e)
      },
    })
  const doBuild = () =>
    build.mutate(v.id, {
      onSuccess: (r) => setJobId(r.job_id),
      onError: onError("Couldn't start the build"),
    })

  const idx = v.index
  const canBuild = !!idx && idx.status !== 'ready' && idx.status !== 'building' && idx.status !== 'pending'
  const liveJob = jobId ?? idx?.job_id ?? null
  const nRebuild = (estimate?.changes ?? []).filter((c) => c.effect === 'rebuild').length

  return (
    <Card padding="lg" className="min-w-0 flex-1" role="region" aria-labelledby="version-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="version-title" className="text-display text-text-primary">v{v.version}</h2>
            {v.active && <Badge tone="accent" icon={<CircleCheck aria-hidden />}>active</Badge>}
            {idx && <StatusBadge status={idx.status} />}
          </div>
          <p className="mt-1 text-body text-text-primary">{v.note || <span className="text-text-tertiary">No note</span>}</p>
          <p className="mt-1 text-body-sm text-text-tertiary">
            Created {formatDateTime(v.created_at)} · index hash <span className="font-mono text-mono-sm">{shortHash(v.index_config_hash)}</span>
            {idx && idx.status === 'ready' && (
              <>
                {' · '}
                {formatNumber(idx.chunk_count)} chunks · {storeLabel(idx.store)}
                {idx.dim ? ` · ${idx.dim}d` : ''}
              </>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {idx?.status === 'ready' && (
            <a
              href={`${API_BASE}/projects/${project.id}/versions/${v.id}/export`}
              download
              className={buttonClasses({ variant: 'secondary', className: 'gap-1.5' })}
              title="Download a standalone Python project with this version's index and pipeline — runs without RAGLabs"
            >
              <Download size={14} aria-hidden />
              Export RAG
            </a>
          )}
          {canBuild && (
            <Button variant="secondary" icon={<Play size={14} aria-hidden />} loading={build.isPending} onClick={doBuild}>
              Build
            </Button>
          )}
          {!v.active && (
            <Button variant="primary" onClick={() => setConfirm(true)}>
              Make active
            </Button>
          )}
        </div>
      </div>

      {idx?.status === 'failed' && idx.error && (
        <Banner tone="danger" title="Build failed" className="mt-4">
          {idx.error}
        </Banner>
      )}

      {liveJob && (
        <div className="mt-4">
          <JobProgress jobId={liveJob} projectId={project.id} title={`Building v${v.version} index`} />
        </div>
      )}

      <section className="mt-6" aria-labelledby="changes-title">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 id="changes-title" className="text-heading text-text-primary">
            {compareLabel ? `Changes vs ${compareLabel}` : 'Changes'}
          </h3>
          {all.length > 1 && (
            <label className="flex items-center gap-2 text-body-sm text-text-secondary">
              Compare with
              <Select
                size="sm"
                options={compareOptions}
                value={compareTo}
                onChange={(e) => setCompareTo(e.target.value)}
                wrapperClassName="w-56"
              />
            </label>
          )}
        </div>
        {loadingChanges ? (
          <div className="flex items-center gap-2 text-body-sm text-text-secondary">
            <Spinner size={12} /> Loading diff…
          </div>
        ) : compareTo && diff.isError ? (
          <Banner tone="danger">{errorMessage(diff.error)}</Banner>
        ) : !compareTo && parentV == null ? (
          <p className="text-body text-text-tertiary">First version — nothing to compare against.</p>
        ) : (
          <DiffTable changes={changes ?? []} catalog={nodes.data} />
        )}
      </section>

      <div className="mt-5 border-t border-border-default pt-4 text-body-sm text-text-secondary">
        {v.active ? (
          <span>This is the active version — the Playground and API use it.</span>
        ) : estimate ? (
          <span>
            <span className="text-label text-text-primary">
              {nRebuild} rebuild change{nRebuild === 1 ? '' : 's'} vs active{activeV ? ` v${activeV.version}` : ''}
            </span>
            {' — activating v'}
            {v.version}: {estimate.estimate.message}
          </span>
        ) : estimateM.isError ? (
          <span className="text-danger-fg">{errorMessage(estimateM.error)}</span>
        ) : (
          <span className="flex items-center gap-2">
            <Spinner size={12} /> Estimating what activating v{v.version} would take…
          </span>
        )}
      </div>

      {!!v.activations?.length && (
        <Disclosure label={`Activation history (${v.activations.length})`} className="mt-4">
          <ul className="flex flex-col gap-1.5 text-body-sm text-text-secondary">
            {v.activations.map((a, i) => (
              <li key={`${a.at}-${i}`}>
                Made active <span title={formatDateTime(a.at)}>{formatRelative(a.at)}</span>
                {a.previous_version != null ? `, replacing v${a.previous_version}` : ' as the first version'}
              </li>
            ))}
          </ul>
        </Disclosure>
      )}

      <Disclosure label="Full configuration" className="mt-4">
        <CodeBlock code={JSON.stringify(v.config, null, 2)} title={`v${v.version} config`} maxHeight={420} />
      </Disclosure>

      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title={`Make v${v.version} active?`}
        description="The Playground and API will answer with this version's pipeline."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirm(false)}>Cancel</Button>
            <Button variant="primary" loading={activate.isPending} onClick={doActivate}>
              Make active
            </Button>
          </>
        }
      >
        <ActivationSummary estimate={estimate} />
      </Dialog>
    </Card>
  )
}

function ActivationSummary({ estimate }: { estimate: EstimateResult | null }) {
  if (!estimate) return null
  return (
    <p className="text-body text-text-secondary">
      {estimate.rebuild_needed ? 'Index: ' : ''}
      {estimate.estimate.message}
    </p>
  )
}

