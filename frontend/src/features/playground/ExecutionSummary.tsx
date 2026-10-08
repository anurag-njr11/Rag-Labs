import { Code2 } from 'lucide-react'
import type { Execution, ExecutionStatus } from '@/api/types'
import { Badge, CodeBlock, Disclosure, type BadgeTone } from '@/components/ui'

const STATUS: Record<ExecutionStatus, { label: string; tone: BadgeTone; note: string }> = {
  verified: { label: 'code verified', tone: 'success', note: 'The answer’s code ran in the sandbox and passed the tests.' },
  unverified: { label: "couldn't verify", tone: 'warning', note: 'The tests still failed after the allowed attempts — this is the best attempt, not a checked one.' },
  ran_without_tests: { label: 'ran, untested', tone: 'neutral', note: 'The code ran without errors, but there were no tests to check it against.' },
  missing_dependency: { label: 'not checked', tone: 'neutral', note: '' },
  sandbox_unavailable: { label: 'not checked', tone: 'neutral', note: '' },
  not_applicable: { label: 'no code', tone: 'neutral', note: '' },
}
const SOURCE: Record<string, string> = {
  provided: 'the question’s own tests',
  doctest: '>>> examples from the docs',
  generated: 'tests the model wrote (weaker evidence: code and tests can be wrong together)',
  none: 'no tests',
}

/** FR-3.13–3.16: what happened when the answer's code was run and tested. */
export function ExecutionSummary({ e }: { e: Execution }) {
  if (e.status === 'not_applicable') return null
  const s = STATUS[e.status]
  return (
    <div className="flex flex-col gap-1 text-body-sm">
      <p className="flex flex-wrap items-center gap-2">
        <Code2 size={14} aria-hidden className="text-text-tertiary" />
        <Badge tone={s.tone}>{s.label}</Badge>
        {e.test_source && e.test_source !== 'none' && <span className="text-text-secondary">against {SOURCE[e.test_source]}</span>}
        {(e.attempts ?? 0) > 1 && <span className="text-text-tertiary">· {e.attempts} attempts</span>}
      </p>
      <p className="text-text-tertiary">{e.error || s.note}</p>
      {e.steps.length > 0 && (
        <Disclosure label="Runs" hint={`${e.steps.length}`}>
          <ol className="space-y-2 py-2">
            {e.steps.map((st) => (
              <li key={st.step} className="flex flex-col gap-1">
                <span className={st.ok ? 'text-success-fg' : 'text-danger-fg'}>
                  Run {st.step}: {st.ok ? 'passed' : `failed at the ${st.stage === 'answer' ? 'code itself' : st.stage === 'tests' ? 'tests' : 'sandbox'}`}
                  <span className="text-text-tertiary"> · {Math.round(st.ms)} ms</span>
                </span>
                {st.detail && <CodeBlock code={st.detail} wrap maxHeight={160} />}
              </li>
            ))}
          </ol>
          {e.tests && <><p className="mt-1 text-caption text-text-tertiary">Tests</p><CodeBlock code={e.tests} wrap maxHeight={160} /></>}
        </Disclosure>
      )}
    </div>
  )
}
