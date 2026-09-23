import { useMemo, useState, type FormEvent } from 'react'
import { ExternalLink, Play } from 'lucide-react'
import { errorMessage, useChat, useRun, useRuns } from '@/api/hooks'
import type { ChatResult, RunDetail } from '@/api/types'
import { BACKEND_DOCS_URL } from '@/app/AppLayout'
import { useWorkspace } from '@/app/workspace'
import { Badge, Banner, Button, Card, CodeBlock, CopyButton, Input, Spinner, Tabs, tabPanelProps } from '@/components/ui'

const ORIGIN = (() => {
  try {
    return new URL(BACKEND_DOCS_URL).origin
  } catch {
    return 'http://127.0.0.1:8000'
  }
})()

const EXAMPLE_Q = 'How do I make a field optional with a default?'
type Lang = 'curl' | 'python' | 'js' | 'stream'

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

/** Build a `stream: false` response body (the documented shape) from a stored run. */
function responseFromRun(run: RunDetail): ChatResult {
  const r = run.result ?? {}
  const citations = r.citations ?? []
  return {
    answer: typeof run.answer === 'string' ? run.answer : (r.answer ?? ''),
    citations,
    sources: (r.retrieved ?? []).slice(0, 3).map((c) => ({
      rank: c.rank,
      document: c.document,
      page_start: c.page_start,
      page_end: c.page_end,
      heading_path: c.heading_path,
      found_by: c.found_by,
      scores: c.scores,
      cited: c.cited ?? citations.some((ci) => ci.chunk_id === c.id),
      text: clip(c.text, 120),
    })),
    run_id: run.id,
    totals: {
      ms: Math.round(run.latency_ms ?? 0),
      latency_ms: Math.round(run.latency_ms ?? 0),
      tokens_in: run.tokens_in ?? 0,
      tokens_out: run.tokens_out ?? 0,
      cost_usd: run.cost_usd ?? 0,
    },
  }
}

/** Pretty JSON, but arrays of primitives (and arrays of those, e.g. spans) stay on one line. */
function compactJson(v: unknown, pad = ''): string {
  const flat = (x: unknown): boolean => x === null || typeof x !== 'object' || (Array.isArray(x) && x.every(flat))
  const inline = (x: unknown): string => (Array.isArray(x) ? `[${x.map(inline).join(', ')}]` : JSON.stringify(x) ?? 'null')
  if (flat(v)) return inline(v)
  const next = `${pad}  `
  if (Array.isArray(v)) return `[\n${v.map((x) => next + compactJson(x, next)).join(',\n')}\n${pad}]`
  const entries = Object.entries(v as Record<string, unknown>).filter(([, x]) => x !== undefined)
  return `{\n${entries.map(([k, x]) => `${next}${JSON.stringify(k)}: ${compactJson(x, next)}`).join(',\n')}\n${pad}}`
}

/** Trim long fields so the example stays readable. */
function prettyResponse(res: ChatResult, trimCitations = true): string {
  const body = {
    ...res,
    citations: trimCitations ? res.citations.slice(0, 2) : res.citations,
    sources: res.sources.map((s) => ({ ...s, text: clip(s.text, 120) })),
  }
  if (trimCitations) body.answer = clip(body.answer, 200)
  let json = compactJson(body)
  if (trimCitations && res.citations.length > 2) json = json.replace(/("citations": \[[\s\S]*?)(\n {2}\],)/, `$1,\n    "… ${res.citations.length - 2} more"$2`)
  return json
}

const STATIC_EXAMPLE = `{
  "answer": "Annotate it as \`int | None\` and give it a default, e.g. \`age: int | None = None\` [1]…",
  "citations": [
    {"n": 1, "chunk_id": "…", "document_id": "…", "document": "concepts__models.md",
     "page_start": null, "page_end": null, "heading_path": "Fields > Optional fields", "spans": [[120, 214]]}
  ],
  "sources": [
    {"rank": 1, "document": "concepts__models.md", "page_start": null, "page_end": null,
     "heading_path": "Fields > Optional fields", "found_by": ["dense", "keyword"],
     "scores": {"dense": 0.82, "keyword": 7.1}, "cited": true, "text": "…"}
  ],
  "run_id": "…",
  "totals": {"ms": 1784, "latency_ms": 1784, "tokens_in": 2328, "tokens_out": 151, "cost_usd": 0.0}
}`

export default function ApiTab() {
  const { project } = useWorkspace()
  const url = `${ORIGIN}/api/projects/${project.id}/chat`
  const version = project.active_version?.version
  const [lang, setLang] = useState<Lang>('curl')

  const snippets: Record<Lang, string> = useMemo(() => {
    const body = JSON.stringify({ question: EXAMPLE_Q, stream: false })
    return {
      curl: `curl -X POST ${url} \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`,
      python: `import requests\n\nres = requests.post(\n    "${url}",\n    json={"question": "${EXAMPLE_Q}", "stream": False},\n    timeout=120,\n)\nres.raise_for_status()\ndata = res.json()\nprint(data["answer"])\nfor c in data["citations"]:\n    print(f"[{c['n']}] {c['document']} — {c['heading_path']}")`,
      js: `const res = await fetch("${url}", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify({ question: "${EXAMPLE_Q}", stream: false }),\n})\nif (!res.ok) throw new Error((await res.json()).detail?.message ?? res.statusText)\nconst { answer, citations } = await res.json()`,
      stream: `curl -N -X POST ${url} \\\n  -H "Content-Type: application/json" \\\n  -H "Accept: text/event-stream" \\\n  -d '${JSON.stringify({ question: EXAMPLE_Q, stream: true })}'\n\n# event: run        data: {"type":"run","run_id":"…","version":${version ?? 1},"store":"faiss",…}\n# event: retrieval  data: {"type":"retrieval","results":[…],"trace":[…]}\n# event: token      data: {"type":"token","text":"In Pydantic v2 …"}\n# event: done       data: {"type":"done","answer":"…","citations":[…],"totals":{…},"truncated":false}`,
    }
  }, [url, version])

  // Example response: the latest successful run of this project, else a static example.
  const runs = useRuns(project.id, 10)
  const lastOk = runs.data?.find((r) => r.status === 'ok')
  const run = useRun(lastOk?.id)
  const example = run.data ? prettyResponse(responseFromRun(run.data)) : STATIC_EXAMPLE

  return (
    <div className="mx-auto w-full max-w-[960px] space-y-4 px-4 py-6 sm:px-8">
      <Card padding="lg">
        <h2 className="text-title text-text-primary">Query endpoint</h2>
        <div className="mt-3 flex min-w-0 items-center gap-2 rounded-md border border-border-default bg-bg-subtle py-1 pl-2 pr-1">
          <Badge tone="accent" className="font-mono">POST</Badge>
          <code className="min-w-0 flex-1 truncate font-mono text-mono text-text-primary" title={url}>{url}</code>
          <CopyButton text={url} aria-label="Copy endpoint URL" />
        </div>
        <p className="mt-2 text-body text-text-secondary">
          Uses the active version{version != null ? ` (v${version})` : ''} unless <code className="font-mono text-mono">version_id</code> is given.
          Body: <code className="font-mono text-mono">{'{"question": "…", "version_id"?: "…", "stream"?: false}'}</code>
        </p>
      </Card>

      <Card padding="lg" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-heading text-text-primary">Request</h2>
          <Tabs
            aria-label="Snippet language"
            idPrefix="api-lang"
            size="sm"
            value={lang}
            onChange={setLang}
            items={[
              { value: 'curl', label: 'curl' },
              { value: 'python', label: 'Python' },
              { value: 'js', label: 'JavaScript' },
              { value: 'stream', label: 'Streaming' },
            ]}
          />
        </div>
        <div {...tabPanelProps('api-lang', lang)} tabIndex={-1}>
          <CodeBlock code={snippets[lang]} title={lang === 'stream' ? 'curl · Server-Sent Events' : lang === 'js' ? 'JavaScript' : lang === 'python' ? 'Python' : 'curl'} />
        </div>
      </Card>

      <Card padding="lg" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-heading text-text-primary">Response</h2>
          <span className="text-body-sm text-text-tertiary">
            {runs.isPending || (lastOk && run.isPending) ? (
              <span className="inline-flex items-center gap-1.5"><Spinner size={12} /> Loading your latest run…</span>
            ) : run.data ? (
              'From your latest successful run (long fields trimmed)'
            ) : (
              'Example'
            )}
          </span>
        </div>
        <CodeBlock code={example} title="200 · application/json" maxHeight={420} wrap />
      </Card>

      <TryIt projectId={project.id} />

      <Card padding="lg">
        <h2 className="text-heading text-text-primary">Notes</h2>
        <ul className="mt-2 list-disc space-y-1.5 pl-5 text-body text-text-secondary marker:text-text-tertiary">
          <li>Answers are generated with the active version's pipeline — change it on Configure, switch it on Versions.</li>
          <li><code className="font-mono text-mono">citations[i].n</code> matches the <code className="font-mono text-mono">[n]</code> markers in <code className="font-mono text-mono">answer</code>; <code className="font-mono text-mono">spans</code> are character ranges in the cited chunk.</li>
          <li>
            Set <code className="font-mono text-mono">"stream": true</code> for Server-Sent Events: <code className="font-mono text-mono">status</code>? → <code className="font-mono text-mono">run</code> → <code className="font-mono text-mono">retrieval</code> → <code className="font-mono text-mono">token</code>* → <code className="font-mono text-mono">done</code> | <code className="font-mono text-mono">error</code>. It's a POST, so read it with a streaming HTTP client, not <code className="font-mono text-mono">EventSource</code>.
          </li>
          <li>Errors: <code className="font-mono text-mono">409</code> no documents / index build failed, <code className="font-mono text-mono">502</code> LLM provider error — both as <code className="font-mono text-mono">{'{"detail": {"code", "message"}}'}</code>.</li>
          <li>The server's <code className="font-mono text-mono">.env</code> holds the LLM key; clients need no key in Phase 1.</li>
        </ul>
        <a
          href={BACKEND_DOCS_URL}
          target="_blank"
          rel="noreferrer"
          className="focus-ring mt-3 inline-flex items-center gap-1 rounded-sm text-body text-accent-text hover:text-accent-hover"
        >
          Full OpenAPI reference <ExternalLink size={12} aria-hidden />
        </a>
      </Card>
    </div>
  )
}

function TryIt({ projectId }: { projectId: string }) {
  const chat = useChat(projectId)
  const [q, setQ] = useState(EXAMPLE_Q)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (q.trim()) chat.mutate({ question: q.trim() })
  }
  return (
    <Card padding="lg" className="space-y-3">
      <div>
        <h2 className="text-heading text-text-primary">Try it</h2>
        <p className="mt-0.5 text-body-sm text-text-tertiary">Sends a real non-streaming request and shows the raw JSON.</p>
      </div>
      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
        <Input aria-label="Question" value={q} onChange={(e) => setQ(e.target.value)} wrapperClassName="flex-1" />
        <Button type="submit" variant="primary" loading={chat.isPending} icon={<Play size={14} aria-hidden />} disabled={!q.trim()}>
          Send request
        </Button>
      </form>
      {chat.isPending && <p className="text-body-sm text-text-secondary">Waiting for the full answer — this can take a few seconds…</p>}
      {chat.isError && <Banner tone="danger" title="Request failed.">{errorMessage(chat.error)}</Banner>}
      {chat.data && <CodeBlock code={prettyResponse(chat.data, false)} title="200 · application/json" maxHeight={420} wrap />}
    </Card>
  )
}
