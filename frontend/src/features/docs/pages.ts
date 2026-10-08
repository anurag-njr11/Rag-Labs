/**
 * The docs: content/<slug>.md files, ordered and grouped here. To add a page, drop a Markdown file in
 * content/ (first line `# Title`, then a one-sentence summary paragraph) and list its slug below.
 */
const raw = import.meta.glob('./content/*.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

export interface DocPage { slug: string; title: string; summary: string; text: string; section: string }

const NAV: { section: string; slugs: string[] }[] = [
  { section: 'Get started', slugs: ['introduction', 'quickstart', 'concepts'] },
  { section: 'Project workspace', slugs: ['projects', 'documents', 'configure', 'versions', 'playground'] },
  { section: 'Measure & improve', slugs: ['evaluate', 'sweeps', 'your-rag', 'advanced-evaluation', 'health'] },
  { section: 'Integrate', slugs: ['api', 'data', 'providers', 'cli'] },
  { section: 'Reference', slugs: ['pipeline-reference', 'metrics', 'troubleshooting'] },
]

function load(slug: string, section: string): DocPage {
  const text = raw[`./content/${slug}.md`]
  if (text === undefined) throw new Error(`docs: content/${slug}.md is listed in pages.ts but missing`)
  const [, title = slug] = /^#\s+(.+)$/m.exec(text) ?? []
  const summary = text.split('\n').slice(1).join('\n').trim().split(/\n\s*\n/)[0]?.replace(/\n/g, ' ') ?? ''
  return { slug, title, summary, text, section }
}

export const SECTIONS = NAV.map((n) => ({ section: n.section, pages: n.slugs.map((s) => load(s, n.section)) }))
export const PAGES: DocPage[] = SECTIONS.flatMap((s) => s.pages)
export const pageBySlug = (slug: string | undefined) => PAGES.find((p) => p.slug === slug)

/** Pages whose title or text contains every word of `query`, title matches first. */
export function searchDocs(query: string): DocPage[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return []
  const hit = (p: DocPage) => words.every((w) => `${p.title}\n${p.text}`.toLowerCase().includes(w))
  const inTitle = (p: DocPage) => words.every((w) => p.title.toLowerCase().includes(w))
  return PAGES.filter(hit).sort((a, b) => Number(inTitle(b)) - Number(inTitle(a)))
}
