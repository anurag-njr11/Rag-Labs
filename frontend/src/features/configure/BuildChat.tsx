import { useState } from 'react'
import { MessageSquareCode } from 'lucide-react'
import { errorMessage, useBuildChat } from '@/api/hooks'
import type { BuildChatResult, PipelineConfig } from '@/api/types'
import { Banner, Button, Card, EffectBadge, Input } from '@/components/ui'
import { flashStages } from './BuildChat.utils'

const show = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v))

/** FR-3.25: describe an edit in words → a schema-valid draft change, shown before it's applied. */
export function BuildChat({ projectId, draft, onApply }: { projectId: string; draft: PipelineConfig; onApply: (c: PipelineConfig) => void }) {
  const ask = useBuildChat(projectId)
  const [text, setText] = useState('')
  const [proposal, setProposal] = useState<BuildChatResult | null>(null)
  const go = () => ask.mutate({ instruction: text.trim(), config: draft }, { onSuccess: setProposal, onError: () => setProposal(null) })
  return (
    <Card padding="lg" className="mb-6 flex flex-col gap-3">
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); go() }}>
        <MessageSquareCode size={18} aria-hidden className="text-text-tertiary" />
        <Input aria-label="Describe a change" value={text} maxLength={1000} wrapperClassName="min-w-64 flex-1"
          placeholder="Describe a change — e.g. “add a reranker and switch to hybrid”" onChange={(e) => setText(e.target.value)} />
        <Button type="submit" variant="secondary" loading={ask.isPending} disabled={text.trim().length < 2}>Propose</Button>
      </form>
      {ask.isError && <Banner tone="danger">{errorMessage(ask.error)}</Banner>}
      {proposal && (
        proposal.changes.length === 0 ? (
          <Banner tone={proposal.error ? 'danger' : 'info'} title="No change proposed">{proposal.error || proposal.explanation}</Banner>
        ) : (
          <div className="flex flex-col gap-2 rounded-lg bg-bg-subtle p-3">
            {proposal.explanation && <p className="text-body text-text-primary">{proposal.explanation}</p>}
            <ul className="space-y-1">
              {proposal.changes.map((c) => (
                <li key={`${c.slot}.${c.field}`} className="flex flex-wrap items-center gap-2 text-body-sm">
                  <EffectBadge effect={c.effect} />
                  <code className="font-mono text-mono-sm text-text-primary">{c.slot}.{c.field}</code>
                  <span className="font-mono text-mono-sm text-text-tertiary">{show(c.before)} → </span>
                  <span className="font-mono text-mono-sm text-text-primary">{show(c.after)}</span>
                </li>
              ))}
            </ul>
            {proposal.rebuild && <p className="text-body-sm text-text-secondary">Saving it will re-index your documents.</p>}
            <div className="flex gap-2">
              <Button size="sm" variant="primary" onClick={() => {
                onApply(proposal.config)
                flashStages([...new Set(proposal.changes.map((c) => c.slot))])
                setProposal(null)
                setText('')
              }}>
                Apply to draft
              </Button>
              <Button size="sm" onClick={() => setProposal(null)}>Discard</Button>
            </div>
          </div>
        )
      )}
    </Card>
  )
}
