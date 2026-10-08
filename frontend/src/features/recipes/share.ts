import type { PipelineConfig } from '@/api/types'

export interface SharedRecipe {
  name: string
  description: string
  tags: string[]
  config: PipelineConfig
}

/** A link that carries the recipe itself (base64url JSON in the fragment): works on any install, no server. */
export function shareUrl(r: SharedRecipe): string {
  const json = JSON.stringify({ name: r.name, description: r.description, tags: r.tags, config: r.config })
  const b64 = btoa(String.fromCharCode(...new TextEncoder().encode(json)))
  return `${window.location.origin}/recipes#recipe=${b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`
}

/** The recipe in a link's fragment, or null when there's none or it doesn't decode. */
export function readShared(hash: string): SharedRecipe | null {
  const m = /recipe=([A-Za-z0-9_-]+)/.exec(hash)
  if (!m) return null
  try {
    const b64 = m[1].replace(/-/g, '+').replace(/_/g, '/')
    const bytes = Uint8Array.from(atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4)), (c) => c.charCodeAt(0))
    const r = JSON.parse(new TextDecoder().decode(bytes)) as SharedRecipe
    return typeof r?.name === 'string' && r.config && typeof r.config === 'object'
      ? { name: r.name.slice(0, 80), description: String(r.description ?? '').slice(0, 600), tags: Array.isArray(r.tags) ? r.tags.slice(0, 8) : [], config: r.config }
      : null
  } catch {
    return null
  }
}
