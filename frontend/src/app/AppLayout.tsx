import { Suspense } from 'react'
import { Link, Outlet } from 'react-router-dom'
import { Layers, Moon, Sun } from 'lucide-react'
import { Badge, Button, Spinner } from '@/components/ui'
import { useTheme } from './theme'

/** Backend's interactive API docs (FastAPI). */
export const BACKEND_DOCS_URL = 'http://127.0.0.1:8000/docs'

/** Top bar height in px — also exposed as CSS var --topbar-h for sticky offsets. */
export const TOPBAR_H = 52

export function PageFallback() {
  return (
    <div className="flex flex-1 items-center justify-center py-24 text-text-tertiary">
      <Spinner size={20} />
    </div>
  )
}

/** App chrome: skip link + 52px sticky top bar + routed content. */
export function AppLayout() {
  const [theme, setTheme] = useTheme()
  return (
    <div className="flex min-h-dvh flex-col" style={{ ['--topbar-h' as string]: `${TOPBAR_H}px` }}>
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-bg-surface px-3 py-2 text-label shadow-md focus:not-sr-only focus:fixed focus:left-4 focus:top-2"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 flex h-[52px] shrink-0 items-center justify-between border-b border-border-default bg-bg-surface px-4 sm:px-8">
        <Link to="/" className="focus-ring flex items-center gap-2.5 rounded-md" aria-label="RAG Builder — all projects">
          <span className="flex size-6 items-center justify-center rounded-md bg-bg-inverse text-text-inverse">
            <Layers size={14} aria-hidden />
          </span>
          <span className="text-heading text-text-primary">RAG Builder</span>
          <Badge tone="neutral" className="hidden sm:inline-flex">Phase 1</Badge>
        </Link>
        <div className="flex items-center gap-1.5">
          <a
            href={BACKEND_DOCS_URL}
            target="_blank"
            rel="noreferrer"
            className="focus-ring hidden h-8 items-center rounded-md px-3 text-label text-text-secondary hover:bg-bg-subtle hover:text-text-primary sm:inline-flex"
          >
            Docs
          </a>
          <Button
            variant="ghost"
            iconOnly
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            onClick={() => setTheme()}
            icon={theme === 'dark' ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
          />
          <span
            aria-hidden
            className="ml-1 flex size-7 items-center justify-center rounded-full bg-accent-subtle text-caption text-accent-text"
          >
            Y
          </span>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="flex min-h-0 flex-1 flex-col outline-none">
        <Suspense fallback={<PageFallback />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  )
}
