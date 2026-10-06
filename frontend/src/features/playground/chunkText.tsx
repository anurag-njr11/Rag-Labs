import type { ReactNode } from 'react'
import { cn } from '@/components/ui'
import { stripTagsPre } from '@/api/format'
import type { Span } from './chunkText.utils'
import { inlineTag, renderInline } from './markdown.utils'

/** Render text[from, to) with the parts inside `spans` wrapped in <mark>. */
function highlight(text: string, spans: Span[], from = 0, to = text.length): ReactNode[] {
  const out: ReactNode[] = []
  let pos = from
  for (const [a, b] of spans) {
    if (b <= from || a >= to) continue
    const s = Math.max(a, from)
    const e = Math.min(b, to)
    if (s > pos) out.push(stripTagsPre(text.slice(pos, s)))
    out.push(
      <mark key={`${s}-${e}`} className="rounded-[2px] bg-highlight-bg px-px text-text-primary">
        {stripTagsPre(text.slice(s, e))}
      </mark>,
    )
    pos = e
  }
  if (pos < to) out.push(stripTagsPre(text.slice(pos, to)))
  return out
}

const HEADING_LINE = /^(#{1,6})\s+/
const BULLET_LINE = /^(\s*)[-*+]\s+/

/**
 * Light Markdown for chunk text that keeps char offsets intact for highlighting: `#` heading lines render
 * bold, `-`/`*` bullets render as •, and `**bold**` markers are hidden. Everything else stays literal.
 */
function richHighlight(text: string, spans: Span[], from = 0, to = text.length): ReactNode[] {
  const out: ReactNode[] = []
  let pos = from
  let k = 0
  while (pos < to) {
    const nl = text.indexOf('\n', pos)
    const end = nl === -1 || nl >= to ? to : nl
    const line = text.slice(pos, end)
    const h = pos === 0 || text[pos - 1] === '\n' ? HEADING_LINE.exec(line) : null
    const bl = !h && (pos === 0 || text[pos - 1] === '\n') ? BULLET_LINE.exec(line) : null
    let start = pos
    if (h) start += h[0].length
    else if (bl) {
      out.push(`${bl[1]}• `)
      start += bl[0].length
    }
    const body = boldRuns(text, spans, start, end, `l${k++}`)
    out.push(h ? <strong key={`h${k}`} className="font-semibold text-text-primary">{body}</strong> : <span key={`s${k}`}>{body}</span>)
    if (end < to) out.push('\n')
    pos = end + 1
  }
  return out
}

/**
 * Highlighted text[from, to) with `**…**` markers removed and their content bolded, and the parser's inline
 * HTML tags (<sup>, <mark>, <br>, …) rendered as formatting. Tags are hidden, never removed from `text`,
 * so span offsets still line up.
 */
function boldRuns(text: string, spans: Span[], from: number, to: number, key: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /\*\*(?=\S)([\s\S]*?\S)\*\*|<(sup|sub|mark|b|strong|i|em|u)>([\s\S]*?)<\/\2>|<br\s*\/?>/g
  re.lastIndex = from
  let pos = from
  let k = 0
  for (let m = re.exec(text); m && m.index + m[0].length <= to; m = re.exec(text)) {
    if (m.index > pos) out.push(...highlight(text, spans, pos, m.index))
    const end = m.index + m[0].length
    if (m[1] !== undefined) {
      out.push(
        <strong key={`${key}-${k++}`} className="font-semibold text-text-primary">
          {highlight(text, spans, m.index + 2, end - 2)}
        </strong>,
      )
    } else if (m[2] !== undefined) {
      const inner = boldRuns(text, spans, m.index + m[2].length + 2, end - m[2].length - 3, `${key}-${k}`)
      out.push(inlineTag(m[2], inner, `${key}-${k++}`))
    } else {
      out.push('\n')
    }
    pos = end
  }
  if (pos < to) out.push(...highlight(text, spans, pos, to))
  return out
}

type Segment = { kind: 'text'; from: number; to: number } | { kind: 'table'; rows: { cells: string[]; from: number; to: number }[] }

const isRow = (l: string) => /^\s*\|.*\|\s*$/.test(l)
const isSep = (l: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l)
/** Split a Markdown table row on unescaped pipes; `\|` stays a literal pipe inside a cell. */
const cellsOf = (l: string) =>
  l.trim().replace(/^\|/, '').replace(/(?<!\\)\|$/, '').split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'))

/** Split a chunk into prose and Markdown-table segments, keeping char offsets for highlighting. */
function segmentTable(text: string): Segment[] {
  const segs: Segment[] = []
  let off = 0
  let textStart = 0
  const lines = text.split('\n')
  let i = 0
  while (i < lines.length) {
    if (isRow(lines[i]) && i + 1 < lines.length && isSep(lines[i + 1])) {
      if (off > textStart) segs.push({ kind: 'text', from: textStart, to: off })
      const rows: { cells: string[]; from: number; to: number }[] = []
      while (i < lines.length && (isRow(lines[i]) || isSep(lines[i]))) {
        if (!isSep(lines[i])) rows.push({ cells: cellsOf(lines[i]), from: off, to: off + lines[i].length })
        off += lines[i].length + 1
        i++
      }
      segs.push({ kind: 'table', rows })
      textStart = off
      continue
    }
    off += lines[i].length + 1
    i++
  }
  if (text.length > textStart) segs.push({ kind: 'text', from: textStart, to: text.length })
  return segs
}

/** A table chunk rendered as a compact table (mono cells, 1px borders); highlighted rows = cited. */
export function TableChunk({ text, spans }: { text: string; spans: Span[] }) {
  const segs = segmentTable(text)
  if (!segs.some((s) => s.kind === 'table')) return <ProseChunk text={text} spans={spans} />
  return (
    <div className="space-y-2">
      {segs.map((s, i) =>
        s.kind === 'text' ? (
          text.slice(s.from, s.to).trim() ? (
            <p key={i} className="whitespace-pre-wrap break-words text-body-lg text-text-secondary">{richHighlight(text, spans, s.from, s.to)}</p>
          ) : null
        ) : (
          <div key={i} className="overflow-x-auto" tabIndex={0} role="group" aria-label="Table chunk">
            <table className="w-full border-collapse font-mono text-mono-sm">
              <thead>
                <tr>
                  {s.rows[0]?.cells.map((c, j) => (
                    <th key={j} scope="col" className="border border-border-default bg-bg-subtle px-2 py-1 text-left font-medium text-text-secondary">{renderInline(c, undefined, `h${j}`)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {s.rows.slice(1).map((r, j) => {
                  const cited = spans.some(([a, b]) => a < r.to && b > r.from)
                  return (
                    <tr key={j} className={cn(cited && 'bg-highlight-bg')}>
                      {r.cells.map((c, k) => (
                        <td key={k} className="border border-border-default px-2 py-1 align-top text-text-primary">{renderInline(c, undefined, `c${j}-${k}`)}</td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ),
      )}
    </div>
  )
}

/** Plain chunk text with cited spans highlighted. `from` lets a collapsed view start near the first highlight. */
export function ProseChunk({ text, spans, from = 0, className }: { text: string; spans: Span[]; from?: number; className?: string }) {
  return (
    <p className={cn('whitespace-pre-wrap break-words text-body-lg text-text-secondary', className)}>
      {from > 0 && <span className="text-text-tertiary">… </span>}
      {richHighlight(text, spans, from)}
    </p>
  )
}
