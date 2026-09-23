import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { ArrowUp, ChevronUp, History, MessageCircle, Plus, Square, X } from 'lucide-react'
import { errorMessage, useProviders, useRuns, useVersions } from '@/api/hooks'
import { formatMs, formatRelative, storeLabel } from '@/api/format'
import type { Version } from '@/api/types'
import { useWorkspace } from '@/app/workspace'
import { Button, Popover, Select, Spinner, StatusBadge, cn, useToast } from '@/components/ui'
import { Inspector, inspectorSummary, type InspectorFocus, type InspectorTab } from './Inspector'
import { Message } from './Message'
import { isActive, useChatSession, type Turn } from './session'

const SUGGESTIONS = [
  'How do I make a field optional with a default?',
  "Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='abc', input_type=str]",
  'What does model_config do?',
]

function useMediaQuery(q: string) {
  const [m, setM] = useState(() => (typeof window === 'undefined' ? true : window.matchMedia(q).matches))
  useEffect(() => {
    const mq = window.matchMedia(q)
    const on = () => setM(mq.matches)
    on()
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [q])
  return m
}

export default function PlaygroundTab() {
  const { project } = useWorkspace()
  const versions = useVersions(project.id)
  const providers = useProviders()
  const session = useChatSession(project.id)
  const { toast } = useToast()
  const wide = useMediaQuery('(min-width: 900px)')

  const [versionId, setVersionId] = useState<string>('')
  const [draft, setDraft] = useState('')
  const [tab, setTab] = useState<InspectorTab>('sources')
  const [inspectedId, setInspectedId] = useState<string | null>(null) // null = follow latest
  const [focus, setFocus] = useState<InspectorFocus & { n: number | null }>({ chunkId: null, n: null, tick: 0 })
  const [sheetOpen, setSheetOpen] = useState(false)
  const closeSheet = useCallback(() => setSheetOpen(false), [])
  const wideRef = useRef(wide)
  useEffect(() => {
    wideRef.current = wide
  }, [wide])
  const openSheet = useCallback(() => {
    if (!wideRef.current) setSheetOpen(true)
  }, [])

  const activeVersionId = project.active_version_id ?? ''
  const selectedVersionId = versionId || activeVersionId
  const selectedVersion: Version | undefined =
    versions.data?.find((v) => v.id === selectedVersionId) ?? (project.active_version?.id === selectedVersionId ? project.active_version : undefined)

  const gen = selectedVersion?.config.generate
  const providerName = gen?.type
  const provider = providers.data?.find((p) => p.name === providerName)
  const model = (typeof gen?.model === 'string' && gen.model) || provider?.default_model || providerName || ''
  const store = selectedVersion?.config.vector_store
  const indexType = typeof store?.index_type === 'string' && store.type === 'faiss' ? store.index_type : undefined
  const maxTokens = typeof gen?.max_tokens === 'number' ? gen.max_tokens : undefined

  const turns = session.turns
  const inspected: Turn | undefined = (inspectedId && turns.find((t) => t.id === inspectedId)) || turns[turns.length - 1]
  const streaming = session.streaming

  // ------------------------------------------------------------------------ thread scrolling
  const thread = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const onThreadScroll = () => {
    const el = thread.current
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }
  useLayoutEffect(() => {
    const el = thread.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [turns])

  // ------------------------------------------------------------------------ actions
  const input = useRef<HTMLTextAreaElement>(null)
  const send = (q = draft) => {
    const question = q.trim()
    if (!question || streaming) return
    stick.current = true
    setInspectedId(null)
    setFocus((f) => ({ chunkId: null, n: null, tick: f.tick }))
    session.ask(question, versionId || undefined)
    setDraft('')
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }
  // Refocus the composer when a stream ends (it was disabled while streaming).
  const wasStreaming = useRef(false)
  useEffect(() => {
    if (wasStreaming.current && !streaming && wide) input.current?.focus()
    wasStreaming.current = streaming
  }, [streaming, wide])

  const onCite = useCallback((turn: Turn, n: number) => {
    const chunk = turn.retrieved.find((c) => c.context_n === n) ?? turn.retrieved.find((c) => c.id === turn.citations.find((ci) => ci.n === n)?.chunk_id)
    setInspectedId(turn.id)
    setTab('sources')
    setFocus((f) => ({ chunkId: chunk?.id ?? null, n, tick: f.tick + 1 }))
    openSheet()
  }, [openSheet])
  const onShowTrace = useCallback((turn: Turn) => {
    setInspectedId(turn.id)
    setTab('trace')
    openSheet()
  }, [openSheet])
  const onInspect = useCallback((turn: Turn) => {
    setInspectedId(turn.id)
    setTab('sources')
    setFocus((f) => ({ chunkId: null, n: null, tick: f.tick }))
    openSheet()
  }, [openSheet])
  const newChat = () => {
    session.clear()
    setInspectedId(null)
    setFocus((f) => ({ chunkId: null, n: null, tick: f.tick }))
    setDraft('')
    input.current?.focus()
  }

  // ------------------------------------------------------------------------ history
  const [historyOpen, setHistoryOpen] = useState(false)
  const historyBtn = useRef<HTMLButtonElement>(null)
  const runs = useRuns(project.id, 20, { enabled: historyOpen })
  const loadRun = async (id: string) => {
    setHistoryOpen(false)
    try {
      stick.current = true
      const tid = await session.loadRun(id)
      setInspectedId(tid)
    } catch (e) {
      toast({ tone: 'danger', title: 'Could not load that run', description: errorMessage(e) })
    }
  }

  const versionOptions = useMemo(
    () =>
      (versions.data ?? (project.active_version ? [project.active_version] : [])).map((v) => ({
        value: v.id,
        label: `v${v.version}${v.active ? ' · active' : ''}${v.index && v.index.status !== 'ready' ? ` · ${v.index.status.replace('_', ' ')}` : ''}`,
      })),
    [versions.data, project.active_version],
  )

  const inspector = (compact = false) => (
    <Inspector
      turn={inspected}
      tab={tab}
      onTabChange={setTab}
      focus={focus}
      indexType={indexType}
      compact={compact}
      className="h-full"
    />
  )
  const sum = inspectorSummary(inspected)

  return (
    <div className="flex h-[calc(100dvh-var(--chrome-h))] min-h-[480px]">
      {/* ------------------------------------------------------------------ chat pane */}
      <section aria-label="Chat" className="flex min-w-0 flex-[3] flex-col bg-bg-canvas">
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border-default bg-bg-surface px-4 py-2 sm:px-6">
          <label htmlFor="pg-version" className="sr-only">Version</label>
          <Select
            id="pg-version"
            size="sm"
            wrapperClassName="w-[150px]"
            value={selectedVersionId}
            onChange={(e) => setVersionId(e.target.value === activeVersionId ? '' : e.target.value)}
            options={versionOptions}
            disabled={streaming || !versionOptions.length}
          />
          <Button size="sm" variant="ghost" icon={<Plus size={14} aria-hidden />} onClick={newChat} disabled={!turns.length}>
            New chat
          </Button>
          <Button
            ref={historyBtn}
            size="sm"
            variant="ghost"
            icon={<History size={14} aria-hidden />}
            onClick={() => setHistoryOpen((o) => !o)}
            aria-expanded={historyOpen}
            aria-haspopup="dialog"
          >
            History
          </Button>
          <span className="ml-auto truncate font-mono text-mono-sm text-text-tertiary" title="Model · vector store of the selected version">
            {[model, store ? storeLabel(store.type) : ''].filter(Boolean).join(' · ')}
          </span>
        </div>

        <Popover open={historyOpen} onClose={() => setHistoryOpen(false)} anchor={historyBtn} align="start" width={360} aria-label="Recent runs">
          <p className="mb-2 text-label text-text-primary">Recent runs</p>
          {runs.isPending ? (
            <p className="flex items-center gap-2 text-body-sm text-text-secondary"><Spinner size={12} /> Loading…</p>
          ) : runs.isError ? (
            <p className="text-body-sm text-danger-fg">{errorMessage(runs.error)}</p>
          ) : !runs.data?.length ? (
            <p className="text-body-sm text-text-secondary">No questions asked yet.</p>
          ) : (
            <ul className="-mx-1 max-h-80 space-y-0.5 overflow-y-auto">
              {runs.data.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => void loadRun(r.id)}
                    className="focus-ring flex w-full flex-col gap-0.5 rounded-md px-2 py-1.5 text-left hover:bg-bg-subtle"
                  >
                    <span className="line-clamp-2 break-words text-body text-text-primary">{r.question}</span>
                    <span className="flex items-center gap-2 text-body-sm text-text-tertiary">
                      {r.status === 'error' && <StatusBadge status="failed" label="Error" />}
                      {r.status === 'running' && <StatusBadge status="queued" label="Incomplete" />}
                      {r.status !== 'ok' && r.status !== 'error' && r.status !== 'running' && <StatusBadge status={r.status} />}
                      {formatRelative(r.created_at)}
                      {!!r.latency_ms && <span className="font-mono text-mono-sm">{formatMs(r.latency_ms)}</span>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Popover>

        <div ref={thread} onScroll={onThreadScroll} className="relative min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[760px] space-y-8 px-4 py-6 sm:px-6">
            {turns.length === 0 ? (
              <div className="flex flex-col items-center gap-4 py-10 text-center">
                <div className="flex size-10 items-center justify-center rounded-lg bg-bg-subtle text-text-secondary">
                  <MessageCircle size={20} aria-hidden />
                </div>
                <div>
                  <h2 className="text-heading text-text-primary">Ask {project.name}</h2>
                  <p className="mt-1 max-w-md text-body text-text-secondary">
                    Answers cite their sources as [n]. Click a citation to see the passage, how it was found and why it ranked.
                  </p>
                </div>
                <div className="flex w-full max-w-lg flex-col gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => send(s)}
                      className="focus-ring truncate rounded-lg border border-border-default bg-bg-surface px-3 py-2 text-left text-body text-text-secondary shadow-sm hover:border-border-strong hover:text-text-primary"
                      title={s}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              turns.map((t) => (
                <Message
                  key={t.id}
                  turn={t}
                  projectId={project.id}
                  inspected={inspected?.id === t.id}
                  activeN={inspected?.id === t.id ? focus.n : null}
                  maxTokens={maxTokens}
                  onCite={onCite}
                  onShowTrace={onShowTrace}
                  onRetry={(x) => session.retry(x.id)}
                  onStop={session.stop}
                  onInspect={onInspect}
                />
              ))
            )}
          </div>
        </div>

        {/* Mobile: collapsed Inspector summary bar */}
        {!wide && inspected && (
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            aria-expanded={sheetOpen}
            aria-controls="pg-sheet"
            className="focus-ring flex h-12 shrink-0 items-center gap-2 border-t border-border-default bg-bg-surface px-4 text-left text-label text-text-primary"
          >
            {isActive(inspected) && <Spinner size={12} />}
            <span className="truncate">
              Sources {sum.retrieved}
              {inspected.status === 'done' && ` · ${sum.cited} cited`}
              {sum.latency != null && ` · Trace ${formatMs(sum.latency)}`}
            </span>
            <ChevronUp size={16} aria-hidden className="ml-auto text-text-tertiary" />
          </button>
        )}

        {/* Composer */}
        <div className="shrink-0 border-t border-border-default bg-bg-surface px-4 pb-[max(12px,env(safe-area-inset-bottom))] pt-3 sm:px-6">
          <div className="mx-auto w-full max-w-[760px]">
            <div className="relative rounded-lg border border-border-strong bg-bg-surface shadow-sm transition-[border-color,box-shadow] focus-within:border-border-focus focus-within:shadow-[var(--shadow-focus)]">
              <label htmlFor="pg-input" className="sr-only">Ask a question</label>
              <textarea
                id="pg-input"
                ref={input}
                rows={3}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKey}
                disabled={streaming}
                placeholder={streaming ? 'Waiting for the answer…' : 'Ask a question, or paste an error message…'}
                aria-describedby="pg-hint"
                className="block max-h-48 min-h-[76px] w-full resize-none rounded-lg bg-transparent py-2.5 pl-3 pr-14 text-body text-text-primary outline-none placeholder:text-text-tertiary disabled:cursor-not-allowed disabled:text-text-disabled"
              />
              <div className="absolute bottom-2 right-2">
                {streaming ? (
                  <Button variant="secondary" iconOnly size={wide ? 'sm' : 'md'} aria-label="Stop generating" onClick={session.stop} className={cn(!wide && 'size-11')} icon={<Square size={12} aria-hidden />} />
                ) : (
                  <Button
                    variant="primary"
                    iconOnly
                    size={wide ? 'sm' : 'md'}
                    aria-label="Send"
                    onClick={() => send()}
                    disabled={!draft.trim()}
                    className={cn(!wide && 'size-11')}
                    icon={<ArrowUp size={14} aria-hidden />}
                  />
                )}
              </div>
            </div>
            <p id="pg-hint" className="mt-1.5 hidden text-body-sm text-text-tertiary sm:block">
              Enter to send · Shift+Enter for newline · answers cite sources as [n]
            </p>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ inspector */}
      {wide ? (
        <aside className="flex min-w-[380px] flex-[2] flex-col border-l border-border-default bg-bg-surface">{inspector()}</aside>
      ) : (
        sheetOpen && inspected && (
          <BottomSheet onClose={closeSheet}>{inspector(true)}</BottomSheet>
        )
      )}
    </div>
  )
}

/** Mobile bottom sheet (max 70vh) with a drag handle; Escape / backdrop / handle close it. */
function BottomSheet({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    const onKey = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    if (!ref.current?.contains(document.activeElement)) ref.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      prev?.focus?.()
    }
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden />
      <div
        id="pg-sheet"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label="Inspector"
        tabIndex={-1}
        className="absolute inset-x-0 bottom-0 flex h-[70vh] flex-col rounded-t-xl border-t border-border-default bg-bg-surface pb-[env(safe-area-inset-bottom)] shadow-lg outline-none"
      >
        <div className="relative flex shrink-0 items-center justify-center pt-2">
          <button type="button" onClick={onClose} aria-label="Collapse inspector" className="focus-ring rounded-full px-6 py-1.5">
            <span aria-hidden className="block h-1 w-10 rounded-full bg-border-strong" />
          </button>
          <Button variant="ghost" size="sm" iconOnly aria-label="Close inspector" onClick={onClose} icon={<X size={14} aria-hidden />} className="absolute right-2 top-1.5" />
        </div>
        <div className="min-h-0 flex-1">{children}</div>
      </div>
    </div>
  )
}
