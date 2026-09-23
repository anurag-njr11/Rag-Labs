/** Small display formatters shared by all features. */

const nf = new Intl.NumberFormat('en-US')

export const formatNumber = (n: number | null | undefined): string => (n == null ? '—' : nf.format(n))

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let v = bytes / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`
}

export function formatCost(usd: number | null | undefined): string {
  if (usd == null) return '—'
  return `$${usd.toFixed(5)}`
}

/** "just now", "5m ago", "2h ago", "yesterday", "3d ago", else "Sep 23". */
export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const s = Math.max(0, Math.round((now - t) / 1000))
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24)
  if (d === 1) return 'yesterday'
  if (d < 7) return `${d}d ago`
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/** "Sep 23, 12:10" */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}, ${d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })}`
}

/** "p.4" or "p.4–6" or "" */
export function formatPages(start: number | null | undefined, end?: number | null): string {
  if (start == null) return ''
  return end != null && end !== start ? `p.${start}–${end}` : `p.${start}`
}

/** First 6 chars of a hash/id. */
export const shortHash = (h: string | null | undefined, n = 6) => (h ? h.slice(0, n) : '—')

/** "vector_store" → "Vector store" */
export function humanize(s: string): string {
  const t = s.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}

/** Display a config value compactly (for diffs). */
export function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'string') return v.length > 60 ? `${v.slice(0, 57)}…` : v
  if (typeof v === 'number') return nf.format(v)
  if (typeof v === 'boolean') return v ? 'on' : 'off'
  return JSON.stringify(v)
}

/** File extension without the dot, lower-case ("md"). */
export function fileExt(name: string): string {
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(i + 1).toLowerCase() : ''
}

const TYPE_LABELS: Record<string, string> = {
  md: 'Markdown', markdown: 'Markdown', mdx: 'MDX', pdf: 'PDF', docx: 'Word', txt: 'Text', rst: 'reST', html: 'HTML', htm: 'HTML',
}
export const fileTypeLabel = (name: string) => TYPE_LABELS[fileExt(name)] ?? (fileExt(name).toUpperCase() || 'File')

const STORE_LABELS: Record<string, string> = {
  faiss: 'FAISS', numpy: 'NumPy', chroma: 'Chroma', qdrant: 'Qdrant', lancedb: 'LanceDB',
}
/** "faiss" → "FAISS" (falls back to humanize). */
export const storeLabel = (s: string | null | undefined) => (s ? STORE_LABELS[s] ?? humanize(s) : '—')
