import type { ReactNode } from 'react'
import { Disclosure } from '@/components/ui'

/** One sentence of what a sub-tab does; the long explanation sits behind "How this works". The sub-tab already names the panel. */
export function PanelIntro({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <div className="max-w-3xl">
      <p className="text-body-lg text-text-secondary">{summary}</p>
      <Disclosure label="How this works" className="mt-1">
        <div className="space-y-2 text-body text-text-secondary">{children}</div>
      </Disclosure>
    </div>
  )
}
