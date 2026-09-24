/**
 * Tiny, safe Markdown renderer for model answers. Builds React elements only — never HTML strings,
 * never dangerouslySetInnerHTML. Supports: paragraphs, headings, fenced code, bullet / numbered lists,
 * blockquotes, inline code, **bold**, *italic* / _italic_, http(s) links and `[n]` / `[1, 2]` citation markers.
 * Tolerates partial input while streaming (an unclosed ``` fence renders as code).
 */
import { Fragment, type ReactNode } from 'react'
import { CodeBlock, cn } from '@/components/ui'

export type RenderCitation = (n: number, key: string) => ReactNode

type Block =
  | { kind: 'p'; text: string }
  | { kind: 'h'; level: number; text: string }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'ul' | 'ol'; items: string[]; start: number }
  | { kind: 'quote'; text: string }

const FENCE = /^\s*(```|~~~)\s*([\w+-]*)\s*$/
const HEADING = /^(#{1,6})\s+(.*)$/
const UL = /^\s*[-*+]\s+(.*)$/
const OL = /^\s*(\d{1,4})[.)]\s+(.*)$/
const QUOTE = /^\s*>\s?(.*)$/

export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let para: string[] = []
  const flushPara = () => {
    if (para.length) blocks.push({ kind: 'p', text: para.join('\n') })
    para = []
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const fence = FENCE.exec(line)
    if (fence) {
      flushPara()
      const body: string[] = []
      i++
      while (i < lines.length && !new RegExp(`^\\s*${fence[1]}\\s*$`).test(lines[i])) body.push(lines[i++])
      blocks.push({ kind: 'code', lang: fence[2], text: body.join('\n') })
      continue
    }
    if (!line.trim()) {
      flushPara()
      continue
    }
    const h = HEADING.exec(line)
    if (h) {
      flushPara()
      blocks.push({ kind: 'h', level: h[1].length, text: h[2] })
      continue
    }
    const ul = UL.exec(line)
    const ol = OL.exec(line)
    if (ul || ol) {
      flushPara()
      const kind = ul ? 'ul' : 'ol'
      const items: string[] = []
      const start = ol ? Number(ol[1]) : 1
      while (i < lines.length) {
        const m = kind === 'ul' ? UL.exec(lines[i]) : OL.exec(lines[i])
        if (m) items.push(kind === 'ul' ? m[1] : m[2])
        else if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) items[items.length - 1] += `\n${lines[i].trim()}`
        else break
        i++
      }
      i--
      blocks.push({ kind, items, start })
      continue
    }
    const q = QUOTE.exec(line)
    if (q) {
      flushPara()
      const body: string[] = []
      while (i < lines.length && QUOTE.test(lines[i])) body.push(QUOTE.exec(lines[i])![1])
      i--
      blocks.push({ kind: 'quote', text: body.join('\n') })
      continue
    }
    para.push(line)
  }
  flushPara()
  return blocks
}

// ------------------------------------------------------------------------------------------------ inline

// Order matters: code first (its content is literal), then citations, links, bold, italics.
const INLINE =
  /(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)|\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\()|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*\n][\s\S]*?)\*\*|(?<![\w*])\*([^*\s](?:[^*\n]*[^*\s])?)\*(?![\w*])|(?<![\w])_([^_\s](?:[^_\n]*[^_\s])?)_(?![\w])/g

export function renderInline(text: string, cite: RenderCitation | undefined, keyPrefix = 'i'): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let k = 0
  const key = () => `${keyPrefix}-${k++}`
  for (const m of text.matchAll(INLINE)) {
    const idx = m.index ?? 0
    if (idx > last) out.push(text.slice(last, idx))
    if (m[2] !== undefined) {
      out.push(
        <code key={key()} className="rounded-sm bg-bg-subtle px-1 py-px font-mono text-[0.92em] text-text-primary">
          {m[2].replace(/^ (.*) $/, '$1')}
        </code>,
      )
    } else if (m[3] !== undefined) {
      const ns = m[3].split(',').map((s) => Number(s.trim()))
      if (cite) ns.forEach((n) => out.push(cite(n, key())))
      else out.push(m[0])
    } else if (m[4] !== undefined) {
      out.push(
        <a key={key()} href={m[5]} target="_blank" rel="noreferrer noopener" className="text-accent-text underline underline-offset-2 hover:text-accent-hover">
          {renderInline(m[4], cite, key())}
        </a>,
      )
    } else if (m[6] !== undefined) {
      out.push(<strong key={key()} className="font-semibold">{renderInline(m[6], cite, key())}</strong>)
    } else if (m[7] !== undefined || m[8] !== undefined) {
      out.push(<em key={key()}>{renderInline((m[7] ?? m[8])!, cite, key())}</em>)
    }
    last = idx + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/** Inline content, keeping soft line breaks as <br>. */
function inlineWithBreaks(text: string, cite: RenderCitation | undefined, keyPrefix: string): ReactNode[] {
  const lines = text.split('\n')
  return lines.flatMap((l, i) => {
    const parts = renderInline(l, cite, `${keyPrefix}-${i}`)
    return i < lines.length - 1 ? [...parts, <br key={`${keyPrefix}-br-${i}`} />] : parts
  })
}

export interface MarkdownProps {
  text: string
  cite?: RenderCitation
  /** Appended inside the last block (e.g. the streaming caret). */
  trailing?: ReactNode
  className?: string
}

export function Markdown({ text, cite, trailing, className }: MarkdownProps) {
  const blocks = parseBlocks(text)
  const lastIdx = blocks.length - 1
  const tail = (i: number) => (i === lastIdx && trailing ? trailing : null)
  return (
    <div className={cn('space-y-3 break-words text-body text-text-primary', className)}>
      {blocks.map((b, i) => {
        const kp = `b${i}`
        switch (b.kind) {
          case 'p':
            return <p key={kp}>{inlineWithBreaks(b.text, cite, kp)}{tail(i)}</p>
          case 'h': {
            const cls = b.level <= 2 ? 'text-heading' : 'text-label'
            return <p key={kp} role="heading" aria-level={Math.min(6, b.level + 2)} className={cn(cls, 'pt-1 text-text-primary')}>{renderInline(b.text, cite, kp)}{tail(i)}</p>
          }
          case 'code':
            return (
              <Fragment key={kp}>
                <CodeBlock code={b.text} title={b.lang || undefined} />
                {tail(i)}
              </Fragment>
            )
          case 'quote':
            return <blockquote key={kp} className="border-l-2 border-border-strong pl-3 text-text-secondary">{inlineWithBreaks(b.text, cite, kp)}{tail(i)}</blockquote>
          case 'ul':
          case 'ol': {
            const List = b.kind
            return (
              <List key={kp} start={b.kind === 'ol' && b.start !== 1 ? b.start : undefined} className={cn('space-y-1 pl-5', b.kind === 'ul' ? 'list-disc' : 'list-decimal', 'marker:text-text-tertiary')}>
                {b.items.map((it, j) => (
                  <li key={j} className="pl-0.5">
                    {inlineWithBreaks(it, cite, `${kp}-${j}`)}
                    {j === b.items.length - 1 ? tail(i) : null}
                  </li>
                ))}
              </List>
            )
          }
        }
      })}
      {blocks.length === 0 && trailing}
    </div>
  )
}
