import { isCited } from './Sources.utils'
import type { Turn } from './session'

export function inspectorSummary(turn: Turn | undefined): { retrieved: number; inContext: number; cited: number; latency?: number } {
  if (!turn) return { retrieved: 0, inContext: 0, cited: 0 }
  const final = turn.status === 'done'
  return {
    retrieved: turn.retrieved.length,
    inContext: turn.retrieved.filter((c) => c.in_context).length,
    cited: final ? turn.retrieved.filter((c) => isCited(c, turn.citations)).length : 0,
    latency: turn.totals?.latency_ms ?? turn.totals?.ms,
  }
}
