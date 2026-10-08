/** Briefly highlight the stage cards (or canvas nodes) a change touched, nearest first (skipped under reduced motion). */
export function flashStages(slots: string[]) {
  // Form view stage cards or canvas nodes — whichever view is showing.
  const els = slots.map((s) => document.getElementById(`stage-${s}`) ?? document.getElementById(`canvas-${s}`))
    .filter((e): e is HTMLElement => !!e)
  els[0]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  els.forEach((el, i) =>
    el.animate(
      [{ boxShadow: '0 0 0 0 transparent' }, { boxShadow: '0 0 0 3px var(--color-accent-default)' }, { boxShadow: '0 0 0 0 transparent' }],
      { duration: 1400, delay: 300 + i * 200, easing: 'ease-in-out' },
    ),
  )
}
