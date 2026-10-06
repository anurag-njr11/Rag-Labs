import type { JobStage } from '@/api/types'

export const STAGE_LABELS: Record<JobStage, string> = {
  fetch: 'Fetch pages',
  parse: 'Parse documents',
  embed: 'Embed chunks',
  store: 'Write vector store',
  keywords: 'Build keyword index',
  ready: 'Ready',
  index: 'Update index',
  generate: 'Write questions',
  validate: 'Filter generic questions',
  evaluate: 'Score retrieval',
  sweep: 'Score configurations',
  retrieve: 'Search each question',
  judge: 'Check answers against the docs',
  recheck: 'Re-check gaps with a deeper search',
  scan: 'Find overlapping passages',
  contradictions: 'Check for contradictions',
  answer: 'Write answers',
  grade: 'Grade answers',
  grade_cells: 'Grade answers of the best configurations',
  rejudge: 'Re-grade close configurations',
}
