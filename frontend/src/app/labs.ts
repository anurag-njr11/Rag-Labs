import { useSyncExternalStore } from 'react'

/** "Labs": research-grade tools (attested computations, embedding adapter, prompt optimisation) stay out of the way until switched on. */
const KEY = 'raglabs.labs'
const subs = new Set<() => void>()

const read = () => {
  try { return localStorage.getItem(KEY) === 'on' } catch { return false }
}
export function setLabs(on: boolean) {
  try { localStorage.setItem(KEY, on ? 'on' : 'off') } catch { /* blocked storage: lasts until reload */ }
  subs.forEach((f) => f())
}
export const useLabs = () => useSyncExternalStore((cb) => { subs.add(cb); return () => subs.delete(cb) }, read)
