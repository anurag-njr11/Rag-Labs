import { useProviders } from '@/api/hooks'
import { Banner, ButtonLink } from '@/components/ui'

/**
 * "No LLM provider configured" bar. Renders nothing while loading or when any provider is available.
 * `variant="inline"` renders a rounded box instead of the full-width bar (e.g. inside the Playground).
 */
export function ProviderKeyBanner({ variant = 'bar' }: { variant?: 'bar' | 'inline' }) {
  const { data } = useProviders()
  if (!data || data.some((p) => p.available)) return null

  return (
    <Banner
      variant={variant}
      tone="warning"
      title="No LLM provider configured —"
      actions={
        <ButtonLink to="/settings/providers" variant="ghost" size="sm">
          Connect one
        </ButtonLink>
      }
    >
      add an API key (Gemini, OpenAI, Anthropic, …) or a local/custom endpoint
      <span className="hidden text-text-secondary md:inline"> — answers can't be generated until then.</span>
    </Banner>
  )
}
