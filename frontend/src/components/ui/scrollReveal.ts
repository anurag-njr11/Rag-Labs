import type { RefObject } from 'react'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { MOTION, gsap, prefersReducedMotion, useGSAP } from './motion'

// Kept out of motion.tsx and the ui barrel so ScrollTrigger (~40 kB) only loads with the screens that use it.
gsap.registerPlugin(ScrollTrigger)

/**
 * Cards fade/rise into place as they scroll into view (ScrollTrigger.batch). `selector` is scoped to `scope`.
 * Re-runs when `deps` change (e.g. once the cards have rendered).
 */
export function useScrollReveal(scope: RefObject<HTMLElement | null>, selector: string, deps: unknown[] = []) {
  useGSAP(
    () => {
      if (prefersReducedMotion() || !scope.current) return
      const els = gsap.utils.toArray<HTMLElement>(selector, scope.current)
      if (!els.length) return
      gsap.set(els, { opacity: 0, y: 28 })
      ScrollTrigger.batch(els, {
        start: 'top 94%',
        once: true,
        onEnter: (batch) => gsap.to(batch, { opacity: 1, y: 0, duration: 0.55, stagger: 0.08, ease: MOTION.out, clearProps: 'transform,opacity' }),
      })
    },
    { scope, dependencies: deps, revertOnUpdate: true },
  )
}
