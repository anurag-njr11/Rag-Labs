/* oxlint-disable react/only-export-components -- motion helpers + one component */
import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import gsap from 'gsap'
import { ScrollToPlugin } from 'gsap/ScrollToPlugin'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useGSAP } from '@gsap/react'
import { cn } from './cn'

gsap.registerPlugin(useGSAP, ScrollToPlugin, ScrollTrigger)
gsap.defaults({ ease: 'power3.out', duration: 0.26 })

/**
 * Motion tokens. Durations are seconds (GSAP). Keep UI motion short: 160–320ms, ease-out on enter,
 * ease-in on exit. "Reduced motion" speeds the global timeline up 100× so every tween (and its
 * onComplete) still runs, but lands instantly.
 */
export const MOTION = {
  fast: 0.16,
  base: 0.26,
  slow: 0.42,
  out: 'power3.out',
  in: 'power2.in',
  inOut: 'power2.inOut',
  spring: 'back.out(1.7)',
} as const

const reducedQuery = typeof window !== 'undefined' ? window.matchMedia('(prefers-reduced-motion: reduce)') : null
const applyReduced = () => gsap.globalTimeline.timeScale(reducedQuery?.matches ? 100 : 1)
applyReduced()
reducedQuery?.addEventListener('change', applyReduced)

export const prefersReducedMotion = () => !!reducedQuery?.matches

export { gsap, useGSAP, ScrollTrigger }

// ------------------------------------------------------------------------------------------ scrolling

export interface SmoothScrollOptions {
  /** Scroll container; defaults to the window. */
  container?: HTMLElement | Window | null
  /** Pixels to keep above the target (sticky headers). */
  offset?: number
  duration?: number
}

/** GSAP smooth scroll to an element or a y position (window or a scroll container). */
export function smoothScrollTo(target: Element | number | 'max', { container, offset = 0, duration = 0.6 }: SmoothScrollOptions = {}) {
  const scroller = container ?? window
  gsap.killTweensOf(scroller, 'scrollTo')
  return gsap.to(scroller, {
    duration,
    ease: 'power3.inOut',
    scrollTo: { y: target, offsetY: offset, autoKill: true },
    overwrite: 'auto',
  })
}

// ------------------------------------------------------------------------------------------ presence

type Anim = (el: HTMLElement) => gsap.core.Animation

export interface PresenceAnims {
  enter: Anim
  exit: Anim
}

/**
 * Mount/unmount with enter + exit animations. Render the element while `mounted` and attach `ref`.
 * When `open` turns false the element stays mounted until the exit tween finishes.
 */
export function usePresence<T extends HTMLElement = HTMLDivElement>(open: boolean, anims: PresenceAnims) {
  const ref = useRef<T>(null)
  const [mounted, setMounted] = useState(open)
  if (open && !mounted) setMounted(true)
  const animsRef = useRef(anims)
  useLayoutEffect(() => {
    animsRef.current = anims
  })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    gsap.killTweensOf(el)
    const tween = open
      ? animsRef.current.enter(el)
      : animsRef.current.exit(el).eventCallback('onComplete', () => setMounted(false))
    return () => {
      tween.kill()
    }
  }, [open, mounted])

  return { ref, mounted }
}

/** Presets for `usePresence`. */
export const presence = {
  /** Floating panels: popovers, menus, hover cards, tooltips. */
  pop: (placement: 'top' | 'bottom' = 'bottom'): PresenceAnims => {
    const dy = placement === 'top' ? 6 : -6
    return {
      enter: (el) =>
        gsap.fromTo(
          el,
          { opacity: 0, y: dy, scale: 0.96, transformOrigin: placement === 'top' ? '50% 100%' : '50% 0%' },
          { opacity: 1, y: 0, scale: 1, duration: 0.2, ease: MOTION.out, clearProps: 'transform' },
        ),
      exit: (el) => gsap.to(el, { opacity: 0, y: dy / 2, scale: 0.98, duration: 0.12, ease: MOTION.in }),
    }
  },
  /** Height collapse for disclosures and drop-down sections. */
  collapse: (): PresenceAnims => ({
    enter: (el) =>
      gsap.fromTo(
        el,
        { height: 0, opacity: 0, overflow: 'hidden' },
        { height: 'auto', opacity: 1, duration: MOTION.base, ease: MOTION.out, clearProps: 'height,overflow' },
      ),
    exit: (el) => gsap.to(el, { height: 0, opacity: 0, overflow: 'hidden', duration: 0.2, ease: MOTION.inOut }),
  }),
  /** Plain fade (+ small rise). */
  fade: (y = 6): PresenceAnims => ({
    enter: (el) => gsap.fromTo(el, { opacity: 0, y }, { opacity: 1, y: 0, duration: MOTION.base, clearProps: 'transform' }),
    exit: (el) => gsap.to(el, { opacity: 0, y: y / 2, duration: MOTION.fast, ease: MOTION.in }),
  }),
  /** Slide in from the side (panels). */
  slideX: (x = 24): PresenceAnims => ({
    enter: (el) => gsap.fromTo(el, { opacity: 0, x }, { opacity: 1, x: 0, duration: MOTION.base, clearProps: 'transform' }),
    exit: (el) => gsap.to(el, { opacity: 0, x, duration: MOTION.fast, ease: MOTION.in }),
  }),
}

// ------------------------------------------------------------------------------------------ components

/** Animated height disclosure body. Children stay mounted during the collapse. */
export function Collapse({ open, children, className }: { open: boolean; children: ReactNode; className?: string }) {
  const { ref, mounted } = usePresence<HTMLDivElement>(open, presence.collapse())
  if (!mounted) return null
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  )
}

/**
 * Plays a directional slide/fade on `ref` whenever `swapKey` changes (tab panels, wizard steps, routes).
 * `direction`: 1 = content arrives from the right, -1 = from the left, 0 = rise from below,
 * 'auto' = compare numeric keys (higher → from the right).
 */
export function useSwapTransition(ref: RefObject<HTMLElement | null>, swapKey: unknown, direction: number | 'auto' = 0, distance = 28) {
  const prev = useRef(swapKey)
  useLayoutEffect(() => {
    const el = ref.current
    const before = prev.current
    if (!el || Object.is(before, swapKey)) return
    prev.current = swapKey
    const dir =
      direction !== 'auto' ? direction : typeof swapKey === 'number' && typeof before === 'number' ? Math.sign(swapKey - before) : 0
    const from = dir === 0 ? { opacity: 0, y: 10 } : { opacity: 0, x: dir * distance }
    const t = gsap.fromTo(el, from, { opacity: 1, x: 0, y: 0, duration: 0.34, ease: MOTION.out, clearProps: 'transform,opacity' })
    return () => {
      t.progress(1).kill()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run only when the key changes
  }, [swapKey])
}

/** Staggered entrance for the direct children (or `selector` matches) of `ref`, once `ready` is true. */
export function useStaggerIn(ref: RefObject<HTMLElement | null>, ready: boolean, { selector, y = 14, stagger = 0.045 }: { selector?: string; y?: number; stagger?: number } = {}) {
  const done = useRef(false)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !ready || done.current) return
    done.current = true
    const targets = selector ? el.querySelectorAll(selector) : el.children
    if (!targets.length) return
    const t = gsap.fromTo(
      targets,
      { opacity: 0, y },
      { opacity: 1, y: 0, duration: 0.4, stagger: Math.min(stagger, 0.5 / targets.length), ease: MOTION.out, clearProps: 'transform,opacity' },
    )
    return () => {
      t.progress(1).kill()
    }
  }, [ref, ready, selector, y, stagger])
}

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

/** A sliding active indicator for tab lists. Place inside a `relative` container; position via `useIndicator`. */
export function useIndicator(
  container: RefObject<HTMLElement | null>,
  indicator: RefObject<HTMLElement | null>,
  activeSelector: string,
  deps: unknown[],
  axis: 'x' | 'x-underline' = 'x',
) {
  const placed = useRef(false)
  useLayoutEffect(() => {
    const c = container.current
    const ind = indicator.current
    if (!c || !ind) return
    const place = (animate: boolean) => {
      const a = c.querySelector<HTMLElement>(activeSelector)
      if (!a) {
        gsap.set(ind, { autoAlpha: 0 })
        placed.current = false
        return
      }
      const vars = { x: a.offsetLeft, width: a.offsetWidth, autoAlpha: 1 } as gsap.TweenVars
      if (axis === 'x') Object.assign(vars, { y: a.offsetTop, height: a.offsetHeight })
      if (animate && placed.current) gsap.to(ind, { ...vars, duration: 0.34, ease: 'power3.out', overwrite: 'auto' })
      else gsap.set(ind, vars)
      placed.current = true
    }
    place(true)
    const ro = new ResizeObserver(() => place(false))
    ro.observe(c)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}

/** The indicator element itself. */
export function TabIndicator({ ref, className }: { ref: RefObject<HTMLSpanElement | null>; className?: string }) {
  return <span ref={ref} aria-hidden className={cn('pointer-events-none invisible absolute left-0', className)} />
}
