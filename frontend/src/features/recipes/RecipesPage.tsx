import { useState } from 'react'
import { BookOpen, Link2, Trash2 } from 'lucide-react'
import { errorMessage, useCreateVersionFor, useDeleteRecipe, useForkConfig, useProjects, useRecipes, useSaveRecipe } from '@/api/hooks'
import type { PipelineConfig, Recipe } from '@/api/types'
import { projectPath } from '@/app/workspace'
import { Badge, Banner, Button, ButtonLink, Card, Select, Spinner, useToast } from '@/components/ui'
import { readShared, shareUrl, type SharedRecipe } from './share'

/** The settings that set recipes apart, in a line. */
function summary(c: PipelineConfig): string {
  const r = c.retrieve as Record<string, unknown>
  const bits = [
    `${String(c.chunk.type).replace('_', ' ')} chunks`,
    `${String(r.type)} retrieval${r.query_expansion && r.query_expansion !== 'none' ? ` + ${String(r.query_expansion).replace('_', ' ')}` : ''}`,
    c.rerank.type === 'none' ? 'no reranker' : 'reranked',
    `${String(c.prompt.type).replace('_', ' ')} prompt`,
  ]
  if (c.cache?.type && c.cache.type !== 'none') bits.push('semantic cache')
  if (c.verify?.type === 'grounding_check') bits.push('grounding check')
  if (r.okf_policy) bits.push('OKF-aware')
  return bits.join(' · ')
}

/** FR-3.26: built-in and saved pipeline recipes — share by link, fork into a project. */
export default function RecipesPage() {
  const recipes = useRecipes()
  const save = useSaveRecipe()
  const { toast } = useToast()
  const [shared, setShared] = useState<SharedRecipe | null>(() => readShared(window.location.hash))

  const importShared = () =>
    shared && save.mutate({ ...shared }, {
      onSuccess: () => {
        toast({ tone: 'success', title: `Added “${shared.name}” to your recipes` })
        setShared(null)
        history.replaceState(null, '', '/recipes')
      },
      onError: (e) => toast({ tone: 'danger', title: 'Could not import the recipe', description: errorMessage(e) }),
    })

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-8">
      <header className="max-w-3xl">
        <h1 className="flex items-center gap-2 text-display text-text-primary"><BookOpen size={26} aria-hidden /> Recipes</h1>
        <p className="mt-1 text-body-lg text-text-secondary">
          Pipeline configurations to start from, share and fork. A share link carries the recipe itself, so it works on anyone's
          install. Forking makes it fit the project: a corpus-specific embedding adapter is left out, and an LLM that isn't connected
          here is swapped for the project's own. Measure it on your eval set before you trust it.
        </p>
      </header>

      {shared && (
        <Banner tone="info" title={`Shared recipe: ${shared.name}`}
          actions={<>
            <Button size="sm" variant="primary" onClick={importShared} loading={save.isPending}>Add to my recipes</Button>
            <Button size="sm" onClick={() => { setShared(null); history.replaceState(null, '', '/recipes') }}>Dismiss</Button>
          </>}>
          {shared.description || summary(shared.config)}
        </Banner>
      )}

      {recipes.isPending ? <Spinner label="Loading recipes" /> : recipes.isError ? (
        <Banner tone="danger">{errorMessage(recipes.error)}</Banner>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {(recipes.data ?? []).map((r) => <RecipeCard key={r.id} r={r} />)}
        </div>
      )}
    </div>
  )
}

function RecipeCard({ r }: { r: Recipe }) {
  const projects = useProjects()
  const fork = useForkConfig()
  const createVersion = useCreateVersionFor()
  const del = useDeleteRecipe()
  const { toast } = useToast()
  const [target, setTarget] = useState('')
  const [done, setDone] = useState<{ project: string; version: number; notes: string[] } | null>(null)

  const use = () => {
    const pid = target || projects.data?.[0]?.id
    if (!pid) return
    fork.mutate({ projectId: pid, config: r.config }, {
      onSuccess: (f) => createVersion.mutate({ projectId: pid, body: { config: f.config, note: `Recipe: ${r.name}`.slice(0, 300), activate: true, build: true } }, {
        onSuccess: (v) => setDone({ project: pid, version: v.version.version, notes: f.notes }),
        onError: (e) => toast({ tone: 'danger', title: 'Could not save the version', description: errorMessage(e) }),
      }),
      onError: (e) => toast({ tone: 'danger', title: 'Could not use the recipe', description: errorMessage(e) }),
    })
  }

  return (
    <Card padding="lg" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-heading text-text-primary">{r.name}</h2>
        {r.builtin ? <Badge tone="accent">built-in</Badge> : <Badge tone="neutral">saved</Badge>}
        {r.tags.map((t) => <Badge key={t} tone="neutral">{t}</Badge>)}
      </div>
      {r.description && <p className="text-body text-text-secondary">{r.description}</p>}
      <p className="font-mono text-mono-sm text-text-tertiary">{summary(r.config)}</p>
      <div className="mt-auto flex flex-wrap items-center gap-2">
        {projects.data && projects.data.length > 0 && (
          <>
            <Select aria-label={`Project to use ${r.name} in`} value={target || projects.data[0].id} onChange={(e) => setTarget(e.target.value)}
              options={projects.data.map((p) => ({ value: p.id, label: p.name }))} wrapperClassName="min-w-40" />
            <Button size="sm" variant="primary" onClick={use} loading={fork.isPending || createVersion.isPending}>Use in project</Button>
          </>
        )}
        <Button size="sm" variant="ghost" icon={<Link2 size={12} aria-hidden />}
          onClick={() => { void navigator.clipboard.writeText(shareUrl(r)); toast({ tone: 'success', title: 'Share link copied' }) }}>
          Copy share link
        </Button>
        {!r.builtin && (
          <Button size="sm" variant="ghost" icon={<Trash2 size={12} aria-hidden />} onClick={() => del.mutate(r.id)}>Delete</Button>
        )}
      </div>
      {done && (
        <Banner tone="success" title={`Saved as v${done.version} and activated`}
          actions={<ButtonLink size="sm" to={projectPath(done.project, 'configure')}>Open</ButtonLink>}>
          {done.notes.length ? done.notes.join(' ') : 'It will be re-scored on the eval set if the project has one.'}
        </Banner>
      )}
    </Card>
  )
}
