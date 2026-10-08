/**
 * Markdown renderer for the in-app docs (content/*.md). React elements only, never HTML strings. Supports
 * headings (with anchors), paragraphs, fenced code, flat bullet/numbered lists, tables, `---` rules, and
 * callouts (a blockquote opening with **Note**, **Tip** or **Warning**). Inline syntax and `/docs/...`
 * links come from the shared `renderInline`.
 */
import { Info, Lightbulb, TriangleAlert } from 'lucide-react'
import { CodeBlock, cn } from '@/components/ui'
import { renderInline } from '@/features/playground/markdown.utils'

export interface TocItem { id: string; text: string; level: 2 | 3 }

type Block =
  | { kind: 'h'; level: number; text: string; id: string }
  | { kind: 'p'; text: string }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'callout'; tone: 'note' | 'tip' | 'warning'; text: string }
  | { kind: 'table'; head: string[]; rows: string[][] }
  | { kind: 'hr' }

const FENCE = /^```\s*([\w+-]*)\s*$/
const HEADING = /^(#{1,4})\s+(.*)$/
const UL = /^\s*[-*]\s+(.*)$/
const OL = /^\s*\d{1,3}[.)]\s+(.*)$/
const QUOTE = /^>\s?(.*)$/
const ROW = /^\s*\|.*\|\s*$/
const DIVIDER = /^\s*\|[\s:|-]+\|\s*$/

export const slugify = (t: string) =>
  t.replace(/[`*_]/g, '').toLowerCase().replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '-')

const cells = (row: string) => row.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map((c) => c.replace(/\\\|/g, '|').trim())

function parse(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const out: Block[] = []
  let para: string[] = []
  const flush = () => {
    if (para.length) out.push({ kind: 'p', text: para.join(' ') })
    para = []
  }
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const fence = FENCE.exec(line)
    if (fence) {
      flush()
      const body: string[] = []
      for (i++; i < lines.length && !/^```\s*$/.test(lines[i]); i++) body.push(lines[i])
      out.push({ kind: 'code', lang: fence[1], text: body.join('\n') })
      continue
    }
    if (!line.trim()) { flush(); continue }
    if (/^---+\s*$/.test(line)) { flush(); out.push({ kind: 'hr' }); continue }
    const h = HEADING.exec(line)
    if (h) { flush(); out.push({ kind: 'h', level: h[1].length, text: h[2], id: slugify(h[2]) }); continue }
    if (ROW.test(line) && DIVIDER.test(lines[i + 1] ?? '')) {
      flush()
      const head = cells(line)
      const rows: string[][] = []
      for (i += 2; i < lines.length && ROW.test(lines[i]); i++) rows.push(cells(lines[i]))
      i--
      out.push({ kind: 'table', head, rows })
      continue
    }
    if (UL.test(line) || OL.test(line)) {
      flush()
      const ordered = !UL.test(line)
      const re = ordered ? OL : UL
      const items: string[] = []
      for (; i < lines.length; i++) {
        const m = re.exec(lines[i])
        if (m) items.push(m[1])
        else if (/^\s{2,}\S/.test(lines[i]) && items.length) items[items.length - 1] += ` ${lines[i].trim()}`
        else break
      }
      i--
      out.push({ kind: 'list', ordered, items })
      continue
    }
    if (QUOTE.test(line)) {
      flush()
      const body: string[] = []
      for (; i < lines.length && QUOTE.test(lines[i]); i++) body.push(QUOTE.exec(lines[i])![1])
      i--
      const text = body.join(' ')
      const tone = /^\*\*(note|tip|warning)\*\*/i.exec(text)?.[1].toLowerCase() as 'note' | 'tip' | 'warning' | undefined
      out.push({ kind: 'callout', tone: tone ?? 'note', text })
      continue
    }
    para.push(line.trim())
  }
  flush()
  return out
}

/** h2/h3 headings, for the "On this page" list. */
export function tocOf(src: string): TocItem[] {
  return parse(src).flatMap((b) => (b.kind === 'h' && (b.level === 2 || b.level === 3) ? [{ id: b.id, text: b.text.replace(/[`*]/g, ''), level: b.level } as TocItem] : []))
}

const CALLOUT = {
  note: { icon: Info, cls: 'border-info-border bg-info-bg' },
  tip: { icon: Lightbulb, cls: 'border-success-border bg-success-bg' },
  warning: { icon: TriangleAlert, cls: 'border-warning-border bg-warning-bg' },
} as const

const inline = (t: string, k: string) => renderInline(t, undefined, k, true)

export function DocsMarkdown({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-4 text-body-lg text-text-primary">
      {parse(text).map((b, i) => {
        const k = `b${i}`
        switch (b.kind) {
          case 'h': {
            const anchor = <a href={`#${b.id}`} aria-label={`Link to ${b.text}`} className="ml-2 text-text-tertiary opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100">#</a>
            if (b.level === 1) return <h1 key={k} id={b.id} className="text-display text-text-primary">{inline(b.text, k)}</h1>
            if (b.level === 2) return <h2 key={k} id={b.id} className="group mt-6 scroll-mt-24 border-t border-border-default pt-6 text-title-lg text-text-primary">{inline(b.text, k)}{anchor}</h2>
            return <h3 key={k} id={b.id} className={cn('group mt-2 scroll-mt-24 text-heading-lg text-text-primary')}>{inline(b.text, k)}{anchor}</h3>
          }
          case 'p':
            return <p key={k} className="leading-7 text-text-secondary">{inline(b.text, k)}</p>
          case 'code':
            return <CodeBlock key={k} code={b.text} title={b.lang || undefined} />
          case 'list': {
            const List = b.ordered ? 'ol' : 'ul'
            return (
              <List key={k} className={cn('flex flex-col gap-1.5 pl-6 text-text-secondary marker:text-text-tertiary', b.ordered ? 'list-decimal' : 'list-disc')}>
                {b.items.map((it, j) => <li key={j} className="pl-1 leading-7">{inline(it, `${k}-${j}`)}</li>)}
              </List>
            )
          }
          case 'callout': {
            const { icon: Icon, cls } = CALLOUT[b.tone]
            return (
              <aside key={k} className={cn('flex gap-3 rounded-lg border px-4 py-3 text-body text-text-primary', cls)}>
                <Icon size={16} aria-hidden className="mt-1 shrink-0" />
                <p className="leading-6">{inline(b.text, k)}</p>
              </aside>
            )
          }
          case 'table':
            return (
              <div key={k} className="overflow-x-auto rounded-lg border border-border-default">
                <table className="w-full min-w-[32rem] border-collapse text-left text-body">
                  <thead className="bg-bg-subtle text-label text-text-secondary">
                    <tr>{b.head.map((c, j) => <th key={j} scope="col" className="px-3 py-2 font-semibold">{inline(c, `${k}h${j}`)}</th>)}</tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j} className="border-t border-border-default align-top">
                        {r.map((c, n) => <td key={n} className="px-3 py-2 leading-6 text-text-secondary">{inline(c, `${k}r${j}c${n}`)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          case 'hr':
            return <hr key={k} className="border-border-default" />
        }
      })}
    </div>
  )
}
