/** Minimal fetch wrapper for the RAG Builder API. Surfaces FastAPI `detail` errors as ApiError. */
import type { PipelineFieldError } from './types'

export const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  /** Raw FastAPI `detail` (string | object), or the raw body when it wasn't JSON. */
  readonly detail: unknown
  /** `detail.code` when present (chat errors: 409/502 → {code, message}). */
  readonly code: string | null
  /** Pipeline validation errors from 422 `{detail: {message, errors}}`. */
  readonly fieldErrors: PipelineFieldError[]

  constructor(status: number, detail: unknown, fallback = `Request failed (${status})`) {
    super(detailToMessage(detail) ?? fallback)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    const d = detail as { code?: unknown; errors?: unknown } | null
    this.code = d && typeof d === 'object' && typeof d.code === 'string' ? d.code : null
    this.fieldErrors = d && typeof d === 'object' && Array.isArray(d.errors) ? (d.errors as PipelineFieldError[]) : []
  }
}

function detailToMessage(detail: unknown): string | null {
  if (detail == null) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI request-validation shape: [{loc, msg, type}]
    const msgs = detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : null))
      .filter(Boolean)
    return msgs.length ? msgs.join('; ') : null
  }
  if (typeof detail === 'object') {
    const m = (detail as { message?: unknown }).message
    if (typeof m === 'string') return m
  }
  return null
}

/** Human-readable message for any thrown value (ApiError, Error, string...). */
export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  if (typeof err === 'string') return err
  return 'Something went wrong'
}

export type Query = Record<string, string | number | boolean | null | undefined>

export function buildUrl(path: string, query?: Query): string {
  const url = path.startsWith('/api') ? path : `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`
  if (!query) return url
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null) qs.set(k, String(v))
  const s = qs.toString()
  return s ? `${url}${url.includes('?') ? '&' : '?'}${s}` : url
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  /** JSON-serialised unless it is FormData. */
  body?: unknown
  query?: Query
  signal?: AbortSignal
  headers?: Record<string, string>
}

/** Throws ApiError on non-2xx. Returns `undefined` for 204 / empty bodies. */
export async function throwIfNotOk(res: Response): Promise<void> {
  if (res.ok) return
  let detail: unknown = null
  const text = await res.text().catch(() => '')
  if (text) {
    try {
      const j = JSON.parse(text) as { detail?: unknown }
      detail = j && typeof j === 'object' && 'detail' in j ? j.detail : j
    } catch {
      detail = text
    }
  }
  throw new ApiError(res.status, detail, `${res.status} ${res.statusText || 'Request failed'}`)
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, signal, headers = {} } = opts
  const init: RequestInit = { method, signal, headers: { Accept: 'application/json', ...headers } }
  if (body !== undefined) {
    if (body instanceof FormData) init.body = body
    else {
      init.body = JSON.stringify(body)
      ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
    }
  }
  let res: Response
  try {
    res = await fetch(buildUrl(path, query), init)
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e
    throw new ApiError(0, 'Cannot reach the backend — is it running on port 8000?')
  }
  await throwIfNotOk(res)
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>(path, { method: 'POST', body, query }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  del: <T = void>(path: string) => request<T>(path, { method: 'DELETE' }),
}
