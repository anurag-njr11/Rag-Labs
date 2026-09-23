/** Join class names, skipping falsy values (so `cond && 'cls'` works for any cond type). */
export function cn(...parts: unknown[]): string {
  return parts.filter((p): p is string => typeof p === 'string' && p !== '').join(' ')
}
