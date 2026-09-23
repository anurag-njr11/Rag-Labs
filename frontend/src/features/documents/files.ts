import { formatBytes } from '@/api/format'
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_BYTES, type Document, type UploadResult } from '@/api/types'
import type { StatusValue } from '@/components/ui'

export const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.join(',')
export const ACCEPTED_LABEL = 'PDF, DOCX, Markdown, MDX, TXT, reST, HTML'

export interface RejectedFile {
  name: string
  reason: string
}

/** Split picked/dropped files into accepted and rejected (type / size / empty), matching API.md limits. */
export function validateFiles(files: Iterable<File>): { accepted: File[]; rejected: RejectedFile[] } {
  const accepted: File[] = []
  const rejected: RejectedFile[] = []
  const seen = new Set<string>()
  for (const f of files) {
    const dot = f.name.lastIndexOf('.')
    const ext = dot >= 0 ? f.name.slice(dot).toLowerCase() : ''
    if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) {
      rejected.push({ name: f.name, reason: `Unsupported type${ext ? ` (${ext})` : ''} — use ${ACCEPTED_LABEL}` })
    } else if (f.size > MAX_UPLOAD_BYTES) {
      rejected.push({ name: f.name, reason: `Too large (${formatBytes(f.size)}) — max ${formatBytes(MAX_UPLOAD_BYTES)}` })
    } else if (f.size === 0) {
      rejected.push({ name: f.name, reason: 'File is empty' })
    } else if (seen.has(`${f.name}:${f.size}`)) {
      continue
    } else {
      seen.add(`${f.name}:${f.size}`)
      accepted.push(f)
    }
  }
  return { accepted, rejected }
}

/** One-line summary of an upload response, for toasts. */
export function uploadSummary(r: UploadResult): { title: string; description?: string; tone: 'success' | 'warning' | 'danger' } {
  const parts: string[] = []
  if (r.duplicates.length) parts.push(`${r.duplicates.length} already in the project (${r.duplicates.map((d) => d.filename).join(', ')})`)
  if (r.errors.length) parts.push(r.errors.map((e) => `${e.filename}: ${e.error}`).join(' · '))
  const n = r.created.length
  return {
    title: n ? `Uploaded ${n} file${n === 1 ? '' : 's'}` : 'No new files uploaded',
    description: parts.join(' · ') || undefined,
    tone: r.errors.length && !n ? 'danger' : r.errors.length || r.duplicates.length ? 'warning' : 'success',
  }
}

/** Row status for the documents table. */
export function documentStatus(d: Document, building: boolean): { status: StatusValue; error: string | null } {
  if (d.status === 'failed') return { status: 'failed', error: d.error }
  if (d.index_error) return { status: 'failed', error: d.index_error }
  if (d.chunks != null) return { status: 'indexed', error: null }
  return { status: building ? 'building' : 'uploaded', error: null }
}
