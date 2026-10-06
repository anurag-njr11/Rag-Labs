import { useState } from 'react'
import { CircleCheck, CircleX, ExternalLink, KeyRound, Pencil, Plug, Plus, Server, Trash2 } from 'lucide-react'
import {
  errorMessage,
  useDeleteProvider,
  useProviderModels,
  useProviderPresets,
  useProviders,
  useSaveProvider,
  useTestProvider,
} from '@/api/hooks'
import type { Provider, ProviderInput, ProviderSource, ProviderTestResult } from '@/api/types'
import {
  Badge,
  Banner,
  Button,
  Card,
  Combobox,
  Dialog,
  Disclosure,
  EmptyState,
  Field,
  Input,
  Spinner,
  Switch,
  Textarea,
  useToast,
} from '@/components/ui'

const GRID = 'grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'

const SOURCE_LABEL: Record<ProviderSource, string> = {
  preset: 'Built-in',
  env: 'From .env',
  ui: 'Set here',
  'custom-env': 'Custom · .env',
  'custom-ui': 'Custom',
}

/** Settings → Providers: connect any OpenAI-compatible LLM as the Generate model. */
export default function ProvidersPage() {
  const providers = useProviders()
  const presets = useProviderPresets()
  const del = useDeleteProvider()
  const { toast } = useToast()
  const [editing, setEditing] = useState<{ provider: Provider | null; create: boolean } | null>(null)
  const [toRemove, setToRemove] = useState<Provider | null>(null)

  const enabled = providers.data ?? []
  const enabledNames = new Set(enabled.map((p) => p.name))
  const more = (presets.data ?? []).filter((p) => !enabledNames.has(p.name))

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 py-8 sm:px-12">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-[720px]">
          <h1 className="text-display text-text-primary">LLM providers</h1>
          <p className="mt-1 text-body text-text-secondary">
            The model that writes answers (Configure → Generate) can be any OpenAI-compatible endpoint: a hosted API with
            your own key, a gateway, or a server on your machine. Keys are kept in the local database and never sent back
            to the browser.
          </p>
        </div>
        <Button variant="primary" icon={<Plus size={14} aria-hidden />} onClick={() => setEditing({ provider: null, create: true })}>
          Custom endpoint
        </Button>
      </div>

      {providers.isError && (
        <Banner tone="danger" title="Couldn't load providers —" className="mb-6">
          {errorMessage(providers.error)}
        </Banner>
      )}

      <section aria-labelledby="connected-h" className="mb-10">
        <h2 id="connected-h" className="mb-3 text-title text-text-primary">Generate options</h2>
        {providers.isLoading ? (
          <div className="flex justify-center py-12 text-text-tertiary"><Spinner size={20} /></div>
        ) : (
          <div className={GRID}>
            {enabled.map((p) => (
              <ProviderCard
                key={p.name}
                provider={p}
                onEdit={() => setEditing({ provider: p, create: false })}
                onRemove={p.source === 'ui' || p.source === 'custom-ui' ? () => setToRemove(p) : undefined}
              />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="presets-h">
        <h2 id="presets-h" className="mb-1 text-title text-text-primary">More providers</h2>
        <p className="mb-3 text-body text-text-secondary">
          Connect one with an API key here, or set its <code className="font-mono text-mono">*_API_KEY</code> in{' '}
          <code className="font-mono text-mono">.env</code> and restart. Anything else that speaks the OpenAI API (vLLM,
          LiteLLM, Azure, a company gateway) can be added as a custom endpoint.
        </p>
        {more.length === 0 && !presets.isLoading ? (
          <EmptyState icon={<Plug aria-hidden />} title="Every built-in provider is connected" />
        ) : (
          <div className={GRID}>
            {more.map((p) => (
              <Card key={p.name} className="flex flex-col gap-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-label text-text-primary">{p.title}</h3>
                    <p className="mt-0.5 text-body-sm text-text-secondary">{p.description}</p>
                  </div>
                  {!p.key_required && <Badge tone="info" icon={<Server size={12} aria-hidden />}>Local</Badge>}
                </div>
                <div className="mt-auto flex items-center justify-between gap-2">
                  {p.signup_url ? (
                    <a href={p.signup_url} target="_blank" rel="noreferrer" className="focus-ring inline-flex items-center gap-1 rounded-sm text-body-sm text-accent-text hover:underline">
                      {p.key_required ? 'Get a key' : 'Download'} <ExternalLink size={12} aria-hidden />
                    </a>
                  ) : <span />}
                  <Button size="sm" onClick={() => setEditing({ provider: p, create: false })}>Connect</Button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>

      {editing && (
        <ProviderDialog
          key={editing.provider?.name ?? '__new'}
          provider={editing.provider}
          create={editing.create}
          onClose={() => setEditing(null)}
        />
      )}

      <Dialog
        open={!!toRemove}
        onClose={() => setToRemove(null)}
        size="sm"
        title={toRemove?.custom ? `Remove ${toRemove.title}?` : `Reset ${toRemove?.title}?`}
        description={
          toRemove?.custom
            ? 'Pipeline versions that use it will fail to answer until you pick another model in Configure → Generate.'
            : 'Settings made here are forgotten; values from .env (if any) apply again.'
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setToRemove(null)}>Cancel</Button>
            <Button
              variant="danger"
              loading={del.isPending}
              onClick={() =>
                toRemove &&
                del.mutate(toRemove.name, {
                  onSuccess: () => {
                    toast({ tone: 'success', title: `${toRemove.title} ${toRemove.custom ? 'removed' : 'reset'}` })
                    setToRemove(null)
                  },
                  onError: (e) => toast({ tone: 'danger', title: 'Couldn’t remove provider', description: errorMessage(e) }),
                })
              }
            >
              {toRemove?.custom ? 'Remove' : 'Reset'}
            </Button>
          </>
        }
      />
    </div>
  )
}

function ProviderCard({ provider: p, onEdit, onRemove }: { provider: Provider; onEdit: () => void; onRemove?: () => void }) {
  const test = useTestProvider()
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-label text-text-primary">{p.title}</h3>
          <p className="truncate font-mono text-mono text-text-tertiary" title={p.base_url}>{p.base_url || 'no base URL'}</p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1">
          <Badge tone="neutral">{SOURCE_LABEL[p.source]}</Badge>
          <Badge tone={p.available ? 'success' : 'warning'} dot>{p.available ? 'Configured' : 'Needs setup'}</Badge>
        </div>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-body-sm">
        <dt className="text-text-tertiary">Default model</dt>
        <dd className="truncate font-mono text-mono text-text-primary">{p.default_model || '—'}</dd>
        <dt className="text-text-tertiary">API key</dt>
        <dd className="truncate text-text-primary">
          {p.key_set ? <span className="font-mono text-mono">{p.key_hint}</span> : p.key_required ? <span className="text-text-tertiary">not set</span> : <span className="text-text-tertiary">not needed</span>}
        </dd>
      </dl>
      {!p.available && p.reason && <p className="text-body-sm text-warning-fg">{p.reason}</p>}
      <TestResult result={test.data} error={test.error} />
      <div className="mt-auto flex items-center justify-end gap-1.5">
        {onRemove && (
          <Button variant="ghost" size="sm" iconOnly aria-label={`Remove ${p.title}`} icon={<Trash2 size={14} aria-hidden />} onClick={onRemove} />
        )}
        <Button size="sm" loading={test.isPending} disabled={!p.base_url} onClick={() => test.mutate({ name: p.name })}>Test</Button>
        <Button size="sm" icon={<Pencil size={12} aria-hidden />} onClick={onEdit}>Edit</Button>
      </div>
    </Card>
  )
}

function TestResult({ result, error }: { result?: ProviderTestResult; error?: Error | null }) {
  if (error) return <p className="text-body-sm text-danger-fg">{errorMessage(error)}</p>
  if (!result) return null
  return result.ok ? (
    <p className="flex items-center gap-1.5 text-body-sm text-success-fg">
      <CircleCheck size={14} aria-hidden /> Connected · {result.models} model{result.models === 1 ? '' : 's'} · {result.ms} ms
    </p>
  ) : (
    <p className="flex items-start gap-1.5 text-body-sm text-danger-fg">
      <CircleX size={14} className="mt-0.5 shrink-0" aria-hidden /> {result.error}
    </p>
  )
}

const parseHeaders = (text: string): Record<string, string> =>
  Object.fromEntries(
    text
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.includes(':'))
      .map((l) => {
        const i = l.indexOf(':')
        return [l.slice(0, i).trim(), l.slice(i + 1).trim()]
      })
      .filter(([k]) => k),
  )

const NAME_RE = /^[a-z][a-z0-9_-]{1,31}$/

/** Create a custom endpoint, connect a preset, or edit either. */
function ProviderDialog({ provider: p, create, onClose }: { provider: Provider | null; create: boolean; onClose: () => void }) {
  const save = useSaveProvider()
  const test = useTestProvider()
  const { toast } = useToast()
  const isCustom = create || !!p?.custom
  const [name, setName] = useState(p?.name ?? '')
  const [title, setTitle] = useState(p?.title ?? '')
  const [baseUrl, setBaseUrl] = useState(p?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(p?.default_model ?? '')
  const [keyRequired, setKeyRequired] = useState(p?.key_required ?? false)
  const [reasoning, setReasoning] = useState(p?.supports_reasoning ?? false)
  // Header values are write-only: existing ones show as "Name: (unchanged)" and are kept unless edited.
  const [headersText, setHeadersText] = useState('')
  const models = useProviderModels(!create && p?.available ? p.name : undefined, 'chat')

  const nameError = create && name && !NAME_RE.test(name) ? 'Lowercase letters, digits, - or _; starts with a letter; 2–32 chars.' : undefined
  const canSave = (!create || (NAME_RE.test(name) && baseUrl.trim())) && (!isCustom || baseUrl.trim())

  const body = (): ProviderInput => {
    const b: ProviderInput = { base_url: baseUrl.trim(), default_model: model.trim(), supports_reasoning: reasoning }
    if (apiKey.trim()) b.api_key = apiKey.trim()
    if (isCustom) {
      b.title = title.trim() || name
      b.key_required = keyRequired
    }
    if (headersText.trim()) b.headers = parseHeaders(headersText)
    return b
  }

  const onSave = () =>
    save.mutate(
      { name: create ? name : p!.name, body: body(), create },
      {
        onSuccess: (saved) => {
          toast({
            tone: saved.available ? 'success' : 'warning',
            title: `${saved.title} saved`,
            description: saved.available ? 'Pick it in Configure → Generate. Use Test to check it answers.' : saved.reason,
          })
          onClose()
        },
      },
    )

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={create ? 'Add a custom endpoint' : p?.enabled ? `Edit ${p.title}` : `Connect ${p?.title}`}
      description={
        isCustom
          ? 'Any server that implements the OpenAI chat completions API — vLLM, LiteLLM, TGI, Azure, a company gateway…'
          : p?.description
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            loading={test.isPending}
            disabled={!baseUrl.trim()}
            onClick={() => test.mutate({ name: create ? undefined : p?.name, body: body() })}
          >
            Test connection
          </Button>
          <Button variant="primary" loading={save.isPending} disabled={!canSave} onClick={onSave}>
            {create ? 'Add provider' : 'Save'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {create && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="ID" help={nameError ? undefined : 'Used in pipeline configs and the API key variable.'} error={nameError}>
              {(f) => (
                <Input id={f.id} aria-describedby={f.describedBy} invalid={f.invalid} mono value={name}
                  placeholder="my-vllm" onChange={(e) => setName(e.target.value.toLowerCase())} />
              )}
            </Field>
            <Field label="Display name">
              {(f) => <Input id={f.id} value={title} placeholder="My vLLM server" onChange={(e) => setTitle(e.target.value)} />}
            </Field>
          </div>
        )}
        {!create && isCustom && (
          <Field label="Display name">
            {(f) => <Input id={f.id} value={title} onChange={(e) => setTitle(e.target.value)} />}
          </Field>
        )}
        <Field label="Base URL" help="The URL that /chat/completions and /models hang off, usually ending in /v1.">
          {(f) => (
            <Input id={f.id} aria-describedby={f.describedBy} mono value={baseUrl}
              placeholder="http://localhost:8000/v1" onChange={(e) => setBaseUrl(e.target.value)} />
          )}
        </Field>
        <Field
          label="API key"
          help={
            p?.key_set
              ? `Stored key ${p.key_hint}. Leave empty to keep it.`
              : p
                ? `Or set ${p.key_env} in .env instead.`
                : `Or set ${name ? name.toUpperCase().replace(/[^A-Z0-9]/g, '_') : 'ID'}_API_KEY in .env and restart.`
          }
        >
          {(f) => (
            <Input id={f.id} aria-describedby={f.describedBy} type="password" autoComplete="off" mono
              icon={<KeyRound aria-hidden />} value={apiKey}
              placeholder={p?.key_set ? p.key_hint : isCustom && !keyRequired ? 'optional' : 'sk-…'}
              onChange={(e) => setApiKey(e.target.value)} />
          )}
        </Field>
        <Field label="Default model" help="Used when a pipeline leaves Generate → Model empty. Can be overridden per version.">
          {(f) => (
            <Combobox id={f.id} aria-describedby={f.describedBy} mono value={model} onChange={setModel}
              options={models.data?.models ?? []} loading={models.isFetching} placeholder="e.g. qwen3-32b" />
          )}
        </Field>

        <Disclosure label="Advanced">
          <div className="flex flex-col gap-4 pt-2">
            {isCustom && (
              <Field inline label="Requires an API key" help="Turn off for local servers that accept any key.">
                {(f) => <Switch id={f.id} checked={keyRequired} onChange={setKeyRequired} aria-label="Requires an API key" />}
              </Field>
            )}
            <Field
              inline
              label="Supports reasoning effort"
              help="Whether the endpoint accepts reasoning_effort (incl. 'none'). Off = the Generate default sends nothing."
            >
              {(f) => <Switch id={f.id} checked={reasoning} onChange={setReasoning} aria-label="Supports reasoning effort" />}
            </Field>
            <Field
              label="Extra HTTP headers"
              help={
                p?.headers.length
                  ? `Currently set: ${p.headers.join(', ')}. Entering headers replaces them all.`
                  : 'One per line, "Name: value" — e.g. api-version for Azure, or an org header.'
              }
            >
              {(f) => (
                <Textarea id={f.id} aria-describedby={f.describedBy} mono rows={3} value={headersText}
                  placeholder="X-Org-Id: acme" onChange={(e) => setHeadersText(e.target.value)} />
              )}
            </Field>
          </div>
        </Disclosure>

        <TestResult result={test.data} error={test.error} />
        {save.isError && <Banner tone="danger" title="Couldn’t save —">{errorMessage(save.error)}</Banner>}
      </div>
    </Dialog>
  )
}
