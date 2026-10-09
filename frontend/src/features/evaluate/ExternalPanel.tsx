import { useState } from 'react'
import { Plug, Trash2 } from 'lucide-react'
import { errorMessage, useCreateExternal, useDeleteExternal, useExternalSystems, useTestExternal } from '@/api/hooks'
import type { ExternalConfig, ExternalTestResult } from '@/api/types'
import { Badge, Banner, Button, Card, CodeBlock, Disclosure, Field, Input, useToast } from '@/components/ui'
import { PanelIntro } from './PanelIntro'

const DEFAULTS = { question_field: 'question', answer_path: 'answer', contexts_path: 'contexts', text_path: 'text', source_path: 'source', top_k: 8, timeout_s: 30 }
const MAPPING = [
  ['question_field', 'Question field', 'JSON key the question is sent in'],
  ['answer_path', 'Answer path', 'where the answer is in the response; empty = retrieval only'],
  ['contexts_path', 'Contexts path', 'the list of retrieved passages, e.g. data.hits'],
  ['text_path', 'Text path', 'passage text inside one context; empty = the context is the text'],
  ['source_path', 'Source path', 'file name or URL of the passage; empty = judge on text alone'],
] as const

/** Connect a RAG that runs elsewhere (PRD §8.7): it is scored on the same eval set as RAGLabs pipelines. */
const PY_SNIPPET = `import raglabs

@raglabs.system
def ask(question):
    hits = retriever.invoke(question)          # your code
    return {"answer": chain.invoke(question),
            "contexts": [{"text": h.page_content, "source": h.metadata["source"]} for h in hits]}

raglabs.serve(ask, port=8100)                  # connect it here, or:
print(raglabs.evaluate(ask, "eval.csv"))       # CI: raglabs eval --system my_rag:ask --set eval.csv`

const OTEL_SNIPPET = `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${location.origin.replace('5173', '8000')}/api/otel/v1/traces
# from another machine, add a RAGLabs API key (any scope may export traces):
OTEL_EXPORTER_OTLP_TRACES_HEADERS=Authorization=Bearer%20rl_…`

export function ExternalPanel({ projectId }: { projectId: string }) {
  const systems = useExternalSystems(projectId)
  const create = useCreateExternal(projectId)
  const remove = useDeleteExternal(projectId)
  const test = useTestExternal(projectId)
  const { toast } = useToast()
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [header, setHeader] = useState({ name: '', value: '' })
  const [map, setMap] = useState<Omit<ExternalConfig, 'url' | 'headers'>>(DEFAULTS)
  const [tested, setTested] = useState<ExternalTestResult | null>(null)

  const config = (): ExternalConfig => ({ url: url.trim(), headers: header.name.trim() ? { [header.name.trim()]: header.value } : {}, ...map })
  const fail = (title: string) => (e: Error) => toast({ tone: 'danger', title, description: errorMessage(e) })

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <Card padding="lg" className="flex flex-col gap-5">
        <PanelIntro summary="Score a RAG you already built (LangChain, LlamaIndex, your own API) on the same questions as your pipelines.">
          <p>
            RAGLabs sends <code className="font-mono text-mono">POST {'{"question": "…"}'}</code> to your endpoint and expects the answer and the passages it retrieved:{' '}
            <code className="font-mono text-mono">{'{"answer": "…", "contexts": [{"text": "…", "source": "file.md"}]}'}</code>. Use the response mapping for other shapes.
          </p>
          <p>A passage counts as a hit when it contains the question&apos;s evidence and, if it names a source, that source is the right file. Answers without a source are judged on text alone.</p>
        </PanelIntro>
        <Field label="Name">{(f) => <Input id={f.id} value={name} onChange={(e) => setName(e.target.value)} placeholder="My LangChain RAG" />}</Field>
        <Field label="Endpoint URL" help="Credentials go in the header below, never in the URL.">
          {(f) => <Input id={f.id} mono value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://localhost:9000/ask" />}
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Auth header name (optional)">{(f) => <Input id={f.id} value={header.name} onChange={(e) => setHeader({ ...header, name: e.target.value })} placeholder="Authorization" />}</Field>
          <Field label="Header value" help="Stored encrypted; never shown again.">
            {(f) => <Input id={f.id} type="password" autoComplete="off" value={header.value} onChange={(e) => setHeader({ ...header, value: e.target.value })} placeholder="Bearer …" />}
          </Field>
        </div>
        <Disclosure label="Response mapping" hint="only if your API differs">
          <div className="grid gap-3 pt-3 sm:grid-cols-2">
            {MAPPING.map(([key, label, help]) => (
              <Field key={key} label={label} help={help}>{(f) => <Input id={f.id} mono value={map[key]} onChange={(e) => setMap({ ...map, [key]: e.target.value })} />}</Field>
            ))}
            <Field label="Passages scored per question" help="Hit@k and MRR look at this many.">
              {(f) => <Input id={f.id} type="number" min={1} max={50} value={map.top_k} onChange={(e) => setMap({ ...map, top_k: Math.max(1, Number(e.target.value) || 1) })} />}
            </Field>
          </div>
        </Disclosure>
        <Disclosure label="Your RAG is a Python function" hint="no API needed">
          <div className="flex flex-col gap-2 pt-3 text-body text-text-secondary">
            <p>Serve it on the contract with the <code className="font-mono text-mono">raglabs</code> package, then connect <code className="font-mono text-mono">http://127.0.0.1:8100</code> above. Or score it in-process, in a script or CI, with no server.</p>
            <CodeBlock title="Python" code={PY_SNIPPET} />
          </div>
        </Disclosure>
        <Disclosure label="Per-step latency and tokens" hint="OpenTelemetry">
          <div className="flex flex-col gap-2 pt-3 text-body text-text-secondary">
            <p>
              Every question is sent with a <code className="font-mono text-mono">traceparent</code> header. If your system is instrumented with OpenTelemetry, export its spans here and each
              result shows a step-by-step trace, and the run shows where the time goes. Tokens come from the <code className="font-mono text-mono">gen_ai.usage.*</code> attributes.
            </p>
            <CodeBlock title="Environment of your RAG service" code={OTEL_SNIPPET} />
          </div>
        </Disclosure>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            icon={<Plug size={14} aria-hidden />}
            loading={test.isPending}
            disabled={!url.trim()}
            onClick={() => test.mutate({ config: config() }, { onSuccess: setTested, onError: (e) => { setTested(null); fail('Test failed')(e) } })}
          >
            Test with one question
          </Button>
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={!url.trim() || !name.trim()}
            onClick={() => create.mutate({ name: name.trim(), config: config() }, {
              onSuccess: () => { toast({ tone: 'success', title: 'Connected', description: 'Pick it under Retrieval quality → Run evaluation.' }); setName(''); setUrl(''); setHeader({ name: '', value: '' }); setTested(null) },
              onError: fail('Could not save'),
            })}
          >
            Save
          </Button>
        </div>
        {tested && (
          <div className="flex flex-col gap-2 rounded-lg bg-bg-subtle p-4 text-body" role="status">
            <p className="text-text-secondary">“{tested.question}” → {Math.round(tested.ms)} ms, {tested.contexts.length} passage{tested.contexts.length === 1 ? '' : 's'}</p>
            <p className="text-text-primary">{tested.answer ?? <em className="text-text-tertiary">No answer in the response (retrieval-only).</em>}</p>
            <ol className="flex list-decimal flex-col gap-1 pl-5 text-body-sm text-text-secondary">
              {tested.contexts.slice(0, 3).map((c, i) => (
                <li key={i}><span className="font-mono text-mono-sm text-text-tertiary">{c.external_source || 'no source'}</span> — {c.text.slice(0, 140)}</li>
              ))}
            </ol>
          </div>
        )}
      </Card>
      <Card padding="lg" className="flex flex-col gap-3">
        <h3 className="text-heading-lg text-text-primary">Connected systems</h3>
        {systems.isError && <Banner tone="danger">{errorMessage(systems.error)}</Banner>}
        {systems.data?.length === 0 && <p className="text-body text-text-secondary">None yet. Connect one to compare it with your pipelines.</p>}
        <ul className="flex flex-col gap-2">
          {systems.data?.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-2 rounded-lg border border-border-default px-3 py-2">
              <span className="min-w-0">
                <span className="block truncate text-heading text-text-primary">{s.name}</span>
                <span className="block truncate font-mono text-mono-sm text-text-tertiary" title={s.config.url}>{s.config.url}</span>
                {s.config.header_names.length > 0 && <Badge tone="neutral">{s.config.header_names.join(', ')}</Badge>}
              </span>
              <Button variant="ghost" size="sm" aria-label={`Remove ${s.name}`} icon={<Trash2 size={14} aria-hidden />} onClick={() => remove.mutate(s.id, { onError: fail('Could not remove') })} />
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
