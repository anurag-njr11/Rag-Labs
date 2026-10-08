import { useLayoutEffect, useState, type RefObject } from 'react'

export type Placement = 'top' | 'bottom'

/** Computes a fixed position for a floating element anchored to `anchor` (flips + clamps to the viewport). */
export function useFloating(open: boolean, anchor: RefObject<HTMLElement | null>, floating: RefObject<HTMLElement | null>, placement: Placement, align: 'center' | 'start' | 'end') {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    if (!open) return
    const update = () => {
      const a = anchor.current, f = floating.current
      if (!a || !f) return
      const r = a.getBoundingClientRect()
      const w = f.offsetWidth, h = f.offsetHeight, gap = 6, m = 8
      let top = placement === 'top' ? r.top - h - gap : r.bottom + gap
      if (placement === 'top' && top < m) top = r.bottom + gap
      if (placement === 'bottom' && top + h > window.innerHeight - m && r.top - h - gap > m) top = r.top - h - gap
      let left = align === 'start' ? r.left : align === 'end' ? r.right - w : r.left + r.width / 2 - w / 2
      left = Math.max(m, Math.min(left, window.innerWidth - w - m))
      setPos({ top, left })
    }
    update()
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [open, anchor, floating, placement, align])
  return pos
}

