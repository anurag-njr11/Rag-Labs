import { useSyncExternalStore } from 'react'

/** "Labs": research-grade evaluation tools (embedding adapter, prompt optimisation) stay out of the way until switched on. */
const KEY = 'raglabs.labs'
const subs = new Set<() => void>()

let on = (() => {
  try { return localStorage.getItem(KEY) === 'on' } catch { return false }
})()
export function setLabs(value: boolean) {
  on = value
  try { localStorage.setItem(KEY, value ? 'on' : 'off') } catch { /* blocked storage: lasts until reload */ }
  subs.forEach((f) => f())
}
export const useLabs = () => useSyncExternalStore((cb) => { subs.add(cb); return () => subs.delete(cb) }, () => on)
