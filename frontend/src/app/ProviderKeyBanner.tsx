import { useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { useProviders } from '@/api/hooks'
import { Banner, Button, CodeBlock, Dialog } from '@/components/ui'

/**
 * "No LLM API key configured" bar. Renders nothing while loading or when any provider is available.
 * `variant="inline"` renders a rounded box instead of the full-width bar (e.g. inside the Playground).
 */
export function ProviderKeyBanner({ variant = 'bar' }: { variant?: 'bar' | 'inline' }) {
  const { data } = useProviders()
  const [open, setOpen] = useState(false)
  if (!data || data.some((p) => p.available)) return null

  return (
    <>
      <Banner
        variant={variant}
        tone="warning"
        title="No LLM API key configured —"
        actions={
          <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
            How to
          </Button>
        }
      >
        add <code className="font-mono text-mono">GEMINI_API_KEY</code> or <code className="font-mono text-mono">NVIDIA_API_KEY</code> to{' '}
        <code className="font-mono text-mono">.env</code>
        <span className="hidden text-text-secondary md:inline"> — answers can't be generated until then.</span>
      </Banner>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Add an LLM API key"
        description="Retrieval works without a key, but chat answers need one of these providers."
        footer={<Button variant="primary" onClick={() => setOpen(false)}>Done</Button>}
      >
        <ol className="flex list-decimal flex-col gap-3 pl-5 text-body">
          <li>
            Get a free key:
            <ul className="mt-1 flex flex-col gap-1">
              {data.map((p) => (
                <li key={p.name}>
                  <a href={p.signup_url} target="_blank" rel="noreferrer" className="focus-ring inline-flex items-center gap-1 rounded-sm text-accent-text hover:underline">
                    {p.title} <ExternalLink size={12} aria-hidden />
                  </a>
                  <span className="text-text-tertiary"> — default model <code className="font-mono text-mono">{p.default_model}</code></span>
                </li>
              ))}
            </ul>
          </li>
          <li>
            Add it to the backend's <code className="font-mono text-mono">.env</code>:
            <CodeBlock className="mt-2" code={'GEMINI_API_KEY=your-key\n# or\nNVIDIA_API_KEY=your-key'} />
          </li>
          <li>Restart the backend.</li>
        </ol>
      </Dialog>
    </>
  )
}
