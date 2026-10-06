export type Span = [number, number]

/** Merge/sort spans and clamp them to [0, len). */
export function normalizeSpans(spans: Span[] | undefined, len: number): Span[] {
  const s = (spans ?? [])
    .map(([a, b]) => [Math.max(0, Math.min(a, len)), Math.max(0, Math.min(b, len))] as Span)
    .filter(([a, b]) => b > a)
    .sort((x, y) => x[0] - y[0])
  const out: Span[] = []
  for (const sp of s) {
    const last = out[out.length - 1]
    if (last && sp[0] <= last[1]) last[1] = Math.max(last[1], sp[1])
    else out.push([sp[0], sp[1]])
  }
  return out
}

/** Where a collapsed (4-line) preview should start so the first highlight is visible. */
export function previewStart(text: string, spans: Span[]): number {
  const first = spans[0]?.[0] ?? 0
  if (first < 160) return 0
  const nl = text.lastIndexOf('\n', first - 1)
  const start = nl >= 0 && first - nl < 200 ? nl + 1 : Math.max(0, text.lastIndexOf(' ', first - 60) + 1)
  return start
}
