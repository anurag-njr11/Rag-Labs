import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Ellipsis, Trash2 } from 'lucide-react'
import { formatNumber, formatRelative, storeLabel } from '@/api/format'
import type { Project, Provider } from '@/api/types'
import type { StatusValue } from '@/components/ui'
import { projectPath } from '@/app/workspace'
import { Button, Popover, StatusBadge, cardClasses, cn } from '@/components/ui'

/** Card/Project status: Ready / Building / Failed / No documents (+ Stale / Not built). */
function projectStatus(p: Project): StatusValue {
  const ix = p.index
  if (ix?.job_id || ix?.status === 'building' || ix?.status === 'pending') return 'building'
  if (p.documents === 0) return 'no_documents'
  return ix?.status ?? 'not_built'
}

/** Most recent activity: project creation, active version, last build. */
function updatedAt(p: Project): string {
  const ts = [p.created_at, p.active_version?.created_at, p.index?.finished_at].filter(Boolean) as string[]
  return ts.reduce((a, b) => (new Date(b) > new Date(a) ? b : a))
}

function modelLabel(p: Project, providers: Provider[] | undefined): string {
  const s = p.summary
  if (!s) return '—'
  if (s.model) return s.model
  return providers?.find((x) => x.name === s.generate)?.default_model || s.generate || '—'
}

export function ProjectCard({ project: p, providers, onDelete }: { project: Project; providers?: Provider[]; onDelete: () => void }) {
  const [menu, setMenu] = useState(false)
  const moreRef = useRef<HTMLButtonElement>(null)
  const status = projectStatus(p)
  const chunks = p.index?.chunk_count

  const meta: [string, string, boolean?][] = [
    ['Docs', formatNumber(p.documents), true],
    ['Chunks', chunks ? formatNumber(chunks) : '—', true],
    ['Store', storeLabel(p.summary?.vector_store ?? p.index?.store)],
    ['Model', modelLabel(p, providers), true],
  ]

  return (
    <article className={cardClasses({ interactive: true, padding: 'lg', className: 'relative flex h-full flex-col gap-4' })}>
      <div className="flex items-start justify-between gap-3">
        <h2 className="min-w-0 text-heading text-text-primary">
          {/* Stretched link: the whole card is clickable, other controls sit above it. */}
          <Link
            to={projectPath(p.id)}
            className="focus-ring block truncate rounded-sm after:absolute after:inset-0 after:rounded-lg after:content-['']"
          >
            {p.name}
          </Link>
        </h2>
        <StatusBadge status={status} className="relative" />
      </div>
      <p className={cn('line-clamp-2 min-h-10 text-body', p.description ? 'text-text-secondary' : 'text-text-tertiary')}>
        {p.description || 'No description'}
      </p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border-default pt-4">
        {meta.map(([k, v, mono]) => (
          <div key={k} className="min-w-0">
            <dt className="text-caption text-text-tertiary">{k}</dt>
            <dd className={cn('mt-0.5 truncate text-text-primary', mono ? 'font-mono text-mono' : 'text-body')} title={v}>{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-auto flex items-center justify-between gap-2">
        <span className="text-body-sm text-text-tertiary">
          {p.active_version ? `v${p.active_version.version} · ` : ''}Updated {formatRelative(updatedAt(p))}
        </span>
        <Button
          ref={moreRef}
          variant="ghost"
          size="sm"
          iconOnly
          aria-label={`More actions for ${p.name}`}
          aria-haspopup="dialog"
          aria-expanded={menu}
          className="relative z-10"
          icon={<Ellipsis size={14} aria-hidden />}
          onClick={() => setMenu((m) => !m)}
        />
        <Popover open={menu} onClose={() => setMenu(false)} anchor={moreRef} width={180} className="p-1" aria-label={`Actions for ${p.name}`}>
          <button
            type="button"
            onClick={() => {
              setMenu(false)
              onDelete()
            }}
            className="focus-ring flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-label text-danger-fg hover:bg-danger-bg"
          >
            <Trash2 size={14} aria-hidden /> Delete project
          </button>
        </Popover>
      </div>
    </article>
  )
}
