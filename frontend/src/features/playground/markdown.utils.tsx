import { Fragment, type ReactNode } from 'react'

export type RenderCitation = (n: number, key: string) => ReactNode

// Order matters: code first (its content is literal), then citations, links, bold, italics, then the
// allowlisted inline HTML tags (paired, <br>, and stray unpaired ones, which are dropped).
const INLINE =
  /(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)|\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\()|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*\n][\s\S]*?)\*\*|(?<![\w*])\*([^*\s](?:[^*\n]*[^*\s])?)\*(?![\w*])|(?<![\w])_([^_\s](?:[^_\n]*[^_\s])?)_(?![\w])|<(sup|sub|mark|b|strong|i|em|u)>([\s\S]*?)<\/\9>|<br\s*\/?>|<\/?(?:sup|sub|mark|b|strong|i|em|u)>/g

/**
 * Wrap `children` in the element for an allowlisted tag. A source `<mark>` (a highlight in the PDF) renders
 * unstyled so it can't be confused with the cited-span highlight.
 */
export function inlineTag(tag: string, children: ReactNode, key: string): ReactNode {
  switch (tag) {
    case 'sup':
      return <sup key={key}>{children}</sup>
    case 'sub':
      return <sub key={key}>{children}</sub>
    case 'b':
    case 'strong':
      return <strong key={key} className="font-semibold">{children}</strong>
    case 'i':
    case 'em':
      return <em key={key}>{children}</em>
    case 'u':
      return <u key={key}>{children}</u>
    default:
      return <Fragment key={key}>{children}</Fragment>
  }
}

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
    } else if (m[9] !== undefined) {
      out.push(inlineTag(m[9], renderInline(m[10], cite, key()), key()))
    } else if (m[0].startsWith('<br')) {
      out.push(<br key={key()} />)
    }
    last = idx + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}
