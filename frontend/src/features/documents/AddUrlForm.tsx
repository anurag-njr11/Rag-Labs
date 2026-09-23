import { useState, type FormEvent } from 'react'
import { Globe, Link as LinkIcon } from 'lucide-react'
import { errorMessage, useAddUrl } from '@/api/hooks'
import { Button, Field, Input, Switch, cn } from '@/components/ui'

export interface AddUrlFormProps {
  projectId: string
  /** Called with the job id once the fetch job starts. */
  onStarted: (jobId: string, url: string) => void
  onCancel?: () => void
  /** Layout: 'dialog' puts the actions in a right-aligned footer row. */
  layout?: 'dialog' | 'inline'
  /** false = fetch only; the index is built later (the wizard builds after Configure). Default true. */
  build?: boolean
  className?: string
}

function checkUrl(v: string): string | null {
  if (!v.trim()) return 'Enter a URL'
  try {
    const u = new URL(v.trim())
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return 'Use an http:// or https:// URL'
    return null
  } catch {
    return 'Enter a full URL, e.g. https://docs.pydantic.dev/latest/'
  }
}

/** URL / sitemap import: POST /documents/url → job (fetch, then build). */
export function AddUrlForm({ projectId, onStarted, onCancel, layout = 'dialog', build = true, className }: AddUrlFormProps) {
  const add = useAddUrl(projectId)
  const [url, setUrl] = useState('')
  const [sitemap, setSitemap] = useState(false)
  const [maxPages, setMaxPages] = useState('50')
  const [touched, setTouched] = useState(false)
  const urlError = touched ? checkUrl(url) : null
  const pagesNum = Number(maxPages)
  const pagesError = sitemap && (!Number.isInteger(pagesNum) || pagesNum < 1 || pagesNum > 1000) ? 'Enter a whole number from 1 to 1,000' : null

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (checkUrl(url) || pagesError) return
    add.mutate(
      { url: url.trim(), sitemap, build, ...(sitemap ? { max_pages: pagesNum } : {}) },
      {
        onSuccess: (r) => {
          onStarted(r.job_id, url.trim())
          setUrl('')
          setTouched(false)
        },
      },
    )
  }

  return (
    <form onSubmit={submit} noValidate className={cn('flex flex-col gap-4', className)}>
      <Field label="URL" error={urlError} help={sitemap ? 'A sitemap.xml, or a page whose sitemap should be crawled.' : 'A single web page to fetch and index.'}>
        {(f) => (
          <Input
            id={f.id}
            aria-describedby={f.describedBy}
            invalid={f.invalid}
            mono
            type="url"
            inputMode="url"
            placeholder="https://docs.pydantic.dev/latest/concepts/models/"
            icon={<Globe />}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onBlur={() => url && setTouched(true)}
          />
        )}
      </Field>
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <Field inline label="Crawl sitemap" help="Fetch every page listed in the sitemap." className="min-w-0 flex-1">
          {(f) => <Switch id={f.id} aria-describedby={f.describedBy} checked={sitemap} onChange={setSitemap} />}
        </Field>
        {sitemap && (
          <Field label="Max pages" error={pagesError} className="w-32">
            {(f) => (
              <Input
                id={f.id}
                aria-describedby={f.describedBy}
                invalid={f.invalid}
                mono
                type="number"
                min={1}
                max={1000}
                value={maxPages}
                onChange={(e) => setMaxPages(e.target.value)}
              />
            )}
          </Field>
        )}
      </div>
      {add.isError && (
        <p role="alert" className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-body text-danger-fg">
          {errorMessage(add.error)}
        </p>
      )}
      <div className={cn('flex gap-2', layout === 'dialog' ? 'justify-end border-t border-border-default pt-3' : 'justify-start')}>
        {onCancel && (
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" variant={layout === 'dialog' ? 'primary' : 'secondary'} loading={add.isPending} icon={<LinkIcon size={14} aria-hidden />}>
          {sitemap ? 'Import pages' : 'Add URL'}
        </Button>
      </div>
    </form>
  )
}
