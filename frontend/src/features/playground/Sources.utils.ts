import type { Citation, RetrievedChunk } from '@/api/types'

export function isCited(chunk: RetrievedChunk, citations: Citation[]): boolean {
  return chunk.cited ?? citations.some((c) => c.chunk_id === chunk.id)
}
