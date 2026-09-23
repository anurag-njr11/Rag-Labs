import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, errorMessage, streamChat } from '@/api/hooks'
import type { ChatEvent, ChatTotals, Citation, RetrievedChunk, RunDetail, TraceStep } from '@/api/types'

export type TurnStatus = 'waiting' | 'retrieved' | 'streaming' | 'done' | 'error' | 'stopped'

export interface Turn {
  id: string
  question: string
  versionId?: string
  status: TurnStatus
  /** `status` event text (index being updated first). */
  indexMessage?: string
  runId?: string
  version?: number
  store?: string
  answer: string
  retrieved: RetrievedChunk[]
  trace: TraceStep[]
  citations: Citation[]
  totals?: ChatTotals
  truncated?: boolean
  error?: { code: string; message: string }
  startedAt: number
  firstTokenAt?: number
  endedAt?: number
  /** Loaded from run history rather than streamed in this session. */
  fromHistory?: boolean
}

let seq = 0
const newId = () => `t${Date.now().toString(36)}${(seq++).toString(36)}`

export function isActive(t: Turn | undefined): boolean {
  return !!t && (t.status === 'waiting' || t.status === 'retrieved' || t.status === 'streaming')
}

/** Reduce one chat SSE event into a turn. Pure — also used by tests / history. */
export function applyEvent(t: Turn, ev: ChatEvent, now = Date.now()): Turn {
  switch (ev.type) {
    case 'status':
      return { ...t, indexMessage: ev.message }
    case 'run':
      return { ...t, runId: ev.run_id, version: ev.version, store: ev.store, indexMessage: undefined }
    case 'retrieval':
      return { ...t, status: 'retrieved', retrieved: ev.results, trace: ev.trace }
    case 'token':
      return { ...t, status: 'streaming', answer: t.answer + ev.text, firstTokenAt: t.firstTokenAt ?? now }
    case 'done':
      return {
        ...t,
        status: 'done',
        runId: ev.run_id,
        answer: ev.answer,
        citations: ev.citations,
        retrieved: ev.retrieved,
        trace: ev.trace,
        totals: ev.totals,
        truncated: ev.truncated,
        endedAt: now,
      }
    case 'error':
      return { ...t, status: 'error', error: { code: ev.code, message: ev.message }, endedAt: now }
    default:
      return t
  }
}

/** Rebuild a turn from a stored run (history). */
export function turnFromRun(run: RunDetail): Turn {
  const r = run.result ?? {}
  const created = new Date(run.created_at).getTime()
  // A run the client aborted is left as 'running' by the backend — show it as stopped.
  const status: TurnStatus = run.status === 'ok' ? 'done' : run.status === 'running' ? 'stopped' : 'error'
  const answer = typeof run.answer === 'string' ? run.answer : (r.answer ?? '')
  const events = Array.isArray(run.events) ? run.events : []
  const gen = events.find((s) => s.step === 'generate')
  return {
    id: newId(),
    question: run.question,
    versionId: run.version_id,
    status,
    runId: run.id,
    answer,
    retrieved: (r.retrieved ?? []).map((c) => ({ ...c, cited: c.cited ?? (r.citations ?? []).some((ci) => ci.chunk_id === c.id) })),
    trace: events,
    citations: r.citations ?? [],
    totals: {
      ms: run.latency_ms ?? 0,
      latency_ms: run.latency_ms ?? 0,
      tokens_in: run.tokens_in ?? 0,
      tokens_out: run.tokens_out ?? 0,
      cost_usd: run.cost_usd ?? 0,
    },
    truncated: gen?.payload?.finish_reason === 'length' || undefined,
    error: status === 'error' ? { code: 'error', message: typeof run.error === 'string' ? run.error : 'The run failed.' } : undefined,
    startedAt: created,
    endedAt: created + (run.latency_ms ?? 0),
    fromHistory: true,
  }
}

export function useChatSession(projectId: string) {
  const qc = useQueryClient()
  const [turns, setTurns] = useState<Turn[]>([])
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  const patch = useCallback((id: string, fn: (t: Turn) => Turn) => {
    setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)))
  }, [])

  const run = useCallback(
    async (id: string, question: string, versionId?: string) => {
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac
      try {
        const terminal = await streamChat(
          projectId,
          { question, ...(versionId ? { version_id: versionId } : {}) },
          { signal: ac.signal, onEvent: (ev) => patch(id, (t) => applyEvent(t, ev)) },
        )
        if (!terminal) {
          patch(id, (t) =>
            isActive(t) ? { ...t, status: 'error', error: { code: 'stream_ended', message: 'The stream ended before the answer finished. Try again.' }, endedAt: Date.now() } : t,
          )
        }
      } catch (e) {
        if ((e as Error)?.name === 'AbortError') {
          patch(id, (t) => (isActive(t) ? { ...t, status: 'stopped', endedAt: Date.now() } : t))
        } else {
          patch(id, (t) => ({ ...t, status: 'error', error: { code: 'request_failed', message: errorMessage(e) }, endedAt: Date.now() }))
        }
      } finally {
        if (abortRef.current === ac) abortRef.current = null
        void qc.invalidateQueries({ queryKey: ['projects', projectId, 'runs'] })
      }
    },
    [projectId, patch, qc],
  )

  const ask = useCallback(
    (question: string, versionId?: string) => {
      const id = newId()
      const turn: Turn = { id, question, versionId, status: 'waiting', answer: '', retrieved: [], trace: [], citations: [], startedAt: Date.now() }
      setTurns((ts) => [...ts, turn])
      void run(id, question, versionId)
      return id
    },
    [run],
  )

  /** Re-run a turn in place (after an error / stop). */
  const retry = useCallback(
    (id: string) => {
      const t = turns.find((x) => x.id === id)
      if (!t) return
      patch(id, (x) => ({
        ...x, status: 'waiting', answer: '', retrieved: [], trace: [], citations: [], error: undefined, totals: undefined,
        truncated: undefined, runId: undefined, indexMessage: undefined, startedAt: Date.now(), firstTokenAt: undefined, endedAt: undefined, fromHistory: false,
      }))
      void run(id, t.question, t.versionId)
    },
    [turns, patch, run],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const clear = useCallback(() => {
    abortRef.current?.abort()
    setTurns([])
  }, [])

  const loadRun = useCallback(async (runId: string) => {
    const detail = await api.get<RunDetail>(`/runs/${runId}`)
    const turn = turnFromRun(detail)
    setTurns((ts) => [...ts, turn])
    return turn.id
  }, [])

  return { turns, ask, retry, stop, clear, loadRun, streaming: turns.some(isActive) }
}
