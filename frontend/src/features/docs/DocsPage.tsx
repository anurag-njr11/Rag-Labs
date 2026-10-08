import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, NavLink, useLocation, useParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, ExternalLink, Search } from 'lucide-react'
import { BACKEND_DOCS_URL } from '@/app/AppLayout'
import { EmptyState, Input, cn } from '@/components/ui'
import { DocsMarkdown, tocOf } from './DocsMarkdown'
import { PAGES, SECTIONS, pageBySlug, searchDocs } from './pages'

const linkCls = (active: boolean) =>
  cn('focus-ring block rounded-md px-3 py-1.5 text-body hover:bg-bg-subtle hover:text-text-primary',
    active ? 'bg-accent-subtle font-medium text-accent-text' : 'text-text-secondary')

function Sidebar({ query, setQuery }: { query: string; setQuery: (q: string) => void }) {
  const results = useMemo(() => searchDocs(query), [query])
  return (
    <nav aria-label="Documentation" className="flex flex-col gap-4">
      <Input icon={<Search />} type="search" aria-label="Search the docs" placeholder="Search the docs" value={query} onChange={(e) => setQuery(e.target.value)} />
      {query.trim() ? (
        <ul className="flex flex-col gap-1" aria-label="Search results">
          {results.map((p) => (
            <li key={p.slug}>
              <NavLink to={`/docs/${p.slug}`} onClick={() => setQuery('')} className={({ isActive }) => linkCls(isActive)}>
                <span className="block">{p.title}</span>
                <span className="block text-body-sm font-normal text-text-tertiary">{p.section}</span>
              </NavLink>
            </li>
          ))}
          {results.length === 0 && <li className="px-3 text-body text-text-tertiary">No pages match “{query.trim()}”.</li>}
        </ul>
      ) : (
        SECTIONS.map((s) => (
          <div key={s.section}>
            <h2 className="px-3 pb-1 text-label uppercase tracking-wide text-text-tertiary">{s.section}</h2>
            <ul className="flex flex-col">
              {s.pages.map((p) => (
                <li key={p.slug}><NavLink to={`/docs/${p.slug}`} className={({ isActive }) => linkCls(isActive)}>{p.title}</NavLink></li>
              ))}
            </ul>
          </div>
        ))
      )}
      <a href={BACKEND_DOCS_URL} target="_blank" rel="noreferrer" className="focus-ring mx-3 inline-flex items-center gap-1.5 text-body text-text-secondary hover:text-text-primary">
        API reference (OpenAPI) <ExternalLink size={13} aria-hidden />
      </a>
    </nav>
  )
}

/** "On this page": highlights the heading nearest the top of the viewport. */
function Toc({ items }: { items: ReturnType<typeof tocOf> }) {
  const [active, setActive] = useState('')
  useEffect(() => {
    const els = items.map((i) => document.getElementById(i.id)).filter((e): e is HTMLElement => !!e)
    const io = new IntersectionObserver((entries) => {
      const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
      if (top) setActive(top.target.id)
    }, { rootMargin: '-80px 0px -70% 0px' })
    els.forEach((e) => io.observe(e))
    return () => io.disconnect()
  }, [items])
  if (items.length < 2) return null
  return (
    <nav aria-label="On this page" className="sticky top-[calc(var(--topbar-h)+24px)] flex flex-col gap-1 text-body-sm">
      <h2 className="pb-1 text-label uppercase tracking-wide text-text-tertiary">On this page</h2>
      {items.map((i) => (
        <a key={i.id} href={`#${i.id}`} className={cn('focus-ring rounded-sm py-0.5 hover:text-text-primary', i.level === 3 && 'pl-3', active === i.id ? 'text-accent-text' : 'text-text-secondary')}>{i.text}</a>
      ))}
    </nav>
  )
}

export default function DocsPage() {
  const { slug } = useParams<{ slug: string }>()
  const { hash } = useLocation()
  const [query, setQuery] = useState('')
  const page = pageBySlug(slug)
  const toc = useMemo(() => (page ? tocOf(page.text) : []), [page])

  useEffect(() => {
    document.title = page ? `${page.title} · RAGLabs docs` : 'RAGLabs docs'
    // After layout: scrolling to an anchor on a fresh load, before the article has its height, can't land.
    const raf = requestAnimationFrame(() => {
      if (hash) document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView()
      else window.scrollTo(0, 0)
    })
    return () => cancelAnimationFrame(raf)
  }, [page, hash])

  if (!slug) return <Navigate to={`/docs/${PAGES[0].slug}`} replace />
  if (!page) {
    return (
      <div className="px-4 py-12 sm:px-8">
        <EmptyState title="Page not found" description="That docs page doesn't exist." actions={<Link className="text-accent-text underline" to="/docs">Back to the docs</Link>} />
      </div>
    )
  }
  const i = PAGES.indexOf(page)
  const prev = PAGES[i - 1]
  const next = PAGES[i + 1]
  return (
    <div className="mx-auto grid w-full max-w-[1440px] gap-8 px-4 py-8 sm:px-8 lg:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[240px_minmax(0,1fr)_200px]">
      <aside className="lg:sticky lg:top-[calc(var(--topbar-h)+24px)] lg:max-h-[calc(100dvh-var(--topbar-h)-48px)] lg:self-start lg:overflow-y-auto">
        <Sidebar query={query} setQuery={setQuery} />
      </aside>
      <article className="min-w-0 max-w-3xl">
        <p className="mb-2 text-label uppercase tracking-wide text-accent-text">{page.section}</p>
        <DocsMarkdown text={page.text} />
        <nav aria-label="Previous and next pages" className="mt-12 grid gap-3 border-t border-border-default pt-6 sm:grid-cols-2">
          {prev ? (
            <Link to={`/docs/${prev.slug}`} className="focus-ring flex flex-col gap-1 rounded-lg border border-border-default p-4 hover:bg-bg-subtle">
              <span className="inline-flex items-center gap-1 text-body-sm text-text-tertiary"><ArrowLeft size={13} aria-hidden /> Previous</span>
              <span className="text-heading text-text-primary">{prev.title}</span>
            </Link>
          ) : <span />}
          {next && (
            <Link to={`/docs/${next.slug}`} className="focus-ring flex flex-col items-end gap-1 rounded-lg border border-border-default p-4 text-right hover:bg-bg-subtle">
              <span className="inline-flex items-center gap-1 text-body-sm text-text-tertiary">Next <ArrowRight size={13} aria-hidden /></span>
              <span className="text-heading text-text-primary">{next.title}</span>
            </Link>
          )}
        </nav>
      </article>
      <aside className="hidden xl:block"><Toc items={toc} /></aside>
    </div>
  )
}
