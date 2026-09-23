/**
 * Server-Sent Events helpers.
 *  - `SseParser`: incremental, spec-compliant parser (chunk boundaries anywhere, CRLF/CR/LF, multi-line `data:`,
 *    `:` comments / pings). Used for the POST chat stream.
 *  - `streamChat`: POST /api/projects/{id}/chat with fetch + stream reader.
 *  - `subscribeJobEvents`: EventSource on GET /api/jobs/{id}/events with done/failed auto-close and safe reconnects.
 */
import { ApiError, buildUrl, request, throwIfNotOk } from './client'
import type { ChatBody, ChatEvent, Job, JobEvent } from './types'

export interface SseMessage {
  event: string
  data: string
  id?: string
}

export class SseParser {
  private buf = ''
  private event = ''
  private data: string[] = []
  private id: string | undefined
  /** true when the previous chunk ended in '\r' (so a leading '\n' in the next chunk is part of a CRLF). */
  private pendingCR = false
  private readonly onMessage: (m: SseMessage) => void

  constructor(onMessage: (m: SseMessage) => void) {
    this.onMessage = onMessage
  }

  push(chunk: string): void {
    if (!chunk) return
    if (this.pendingCR && chunk.startsWith('\n')) chunk = chunk.slice(1)
    this.pendingCR = false
    this.buf += chunk
    let start = 0
    for (let i = 0; i < this.buf.length; i++) {
      const c = this.buf[i]
      if (c !== '\n' && c !== '\r') continue
      const line = this.buf.slice(start, i)
      if (c === '\r') {
        if (i + 1 < this.buf.length) {
          if (this.buf[i + 1] === '\n') i++
        } else {
          this.pendingCR = true
        }
      }
      start = i + 1
      this.line(line)
    }
    this.buf = this.buf.slice(start)
  }

  /** Call at end of stream: dispatches a final message that wasn't followed by a blank line. */
  flush(): void {
    if (this.buf) {
      this.line(this.buf)
      this.buf = ''
    }
    this.dispatch()
  }

  private line(line: string): void {
    if (line === '') return this.dispatch()
    if (line.startsWith(':')) return // comment / keep-alive ping
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') this.event = value
    else if (field === 'data') this.data.push(value)
    else if (field === 'id') this.id = value
  }

  private dispatch(): void {
    if (this.data.length) this.onMessage({ event: this.event || 'message', data: this.data.join('\n'), id: this.id })
    this.event = ''
    this.data = []
  }
}

function parseJson(data: string): Record<string, unknown> | null {
  try {
    const v = JSON.parse(data) as unknown
    return v && typeof v === 'object' ? (v as Record<string, unknown>) : null
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------------------------- chat

export interface StreamChatOptions {
  onEvent: (e: ChatEvent) => void
  signal?: AbortSignal
}

/**
 * POST a chat question and stream its SSE events to `onEvent`.
 * Resolves with the terminal event (`done` or `error`), or null if the stream ended without one.
 * Rejects with ApiError for non-2xx responses (404 project/version…) and with an AbortError when `signal` aborts.
 */
export async function streamChat(projectId: string, body: ChatBody, opts: StreamChatOptions): Promise<ChatEvent | null> {
  const res = await fetch(buildUrl(`/projects/${projectId}/chat`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ ...body, stream: true }),
    signal: opts.signal,
  }).catch((e: unknown) => {
    if ((e as Error)?.name === 'AbortError') throw e
    throw new ApiError(0, 'Cannot reach the backend — is it running on port 8000?')
  })
  await throwIfNotOk(res)
  if (!res.body) throw new ApiError(res.status, 'Empty response stream')

  let terminal: ChatEvent | null = null
  const parser = new SseParser((m) => {
    const data = parseJson(m.data)
    if (!data) return
    const ev = { ...data, type: (data.type as string) || m.event } as ChatEvent
    if (ev.type === 'done' || ev.type === 'error') terminal = ev
    opts.onEvent(ev)
  })

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      if (value) parser.push(value)
    }
    parser.flush()
  } finally {
    reader.releaseLock()
  }
  return terminal
}

// ---------------------------------------------------------------------------------------------- jobs

export interface JobSubscription {
  close: () => void
}
export interface JobSubscribeHandlers {
  onEvent: (e: JobEvent) => void
  /** Called before a reconnect: the server replays history, so consumers must clear accumulated state. */
  onReset?: () => void
  /** The job is unknown to the server (404 — e.g. it finished long ago and was evicted). */
  onLost?: () => void
}

const JOB_EVENT_TYPES = ['progress', 'log', 'done', 'failed'] as const

/** Subscribe to GET /api/jobs/{id}/events. Closes itself on `done` / `failed`. */
export function subscribeJobEvents(jobId: string, h: JobSubscribeHandlers): JobSubscription {
  let es: EventSource | null = null
  let closed = false
  let retry: ReturnType<typeof setTimeout> | null = null
  let attempts = 0

  const close = () => {
    closed = true
    if (retry) clearTimeout(retry)
    es?.close()
    es = null
  }

  const handle = (type: string) => (msg: MessageEvent<string>) => {
    const data = parseJson(msg.data)
    if (!data) return
    attempts = 0
    const ev = { ...data, type: (data.type as string) || type } as JobEvent
    h.onEvent(ev)
    if (ev.type === 'done' || ev.type === 'failed') close()
  }

  const open = () => {
    if (closed) return
    es = new EventSource(buildUrl(`/jobs/${jobId}/events`))
    for (const t of JOB_EVENT_TYPES) es.addEventListener(t, handle(t) as EventListener)
    es.onmessage = handle('message')
    es.onerror = () => {
      // Take reconnection into our own hands: check the job, then replay from scratch.
      es?.close()
      es = null
      if (closed) return
      request<Job>(`/jobs/${jobId}`)
        .then((job) => {
          if (closed) return
          if (job.status !== 'running' && job.last && (job.last.type === 'done' || job.last.type === 'failed')) {
            h.onEvent(job.last)
            close()
            return
          }
          if (job.status === 'failed') {
            h.onEvent({ type: 'failed', t: Date.now() / 1000, error: job.error ?? 'Job failed' })
            close()
            return
          }
          scheduleReopen()
        })
        .catch((e: unknown) => {
          if (closed) return
          if (e instanceof ApiError && e.status === 404) {
            h.onLost?.()
            close()
          } else scheduleReopen()
        })
    }
  }

  const scheduleReopen = () => {
    attempts++
    retry = setTimeout(() => {
      h.onReset?.()
      open()
    }, Math.min(1000 * attempts, 5000))
  }

  open()
  return { close }
}
