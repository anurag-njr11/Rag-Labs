import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { CircleCheck, CircleX, Info, TriangleAlert, X } from 'lucide-react'
import { cn } from './cn'
import { MOTION, gsap } from './motion'

export type ToastTone = 'success' | 'danger' | 'info' | 'warning' | 'neutral'
export interface ToastInput {
  title: ReactNode
  description?: ReactNode
  tone?: ToastTone
  /** ms; 0 = sticky. Default 4000 (6000 for danger). */
  duration?: number
  action?: { label: string; onClick: () => void }
}
interface ToastItem extends ToastInput {
  id: number
  /** Playing its exit animation; removed when it finishes. */
  leaving?: boolean
}

interface ToastApi {
  toast: (t: ToastInput) => number
  dismiss: (id: number) => void
}

const Ctx = createContext<ToastApi | null>(null)

const ICON: Record<ToastTone, ReactNode> = {
  success: <CircleCheck size={16} className="text-success-fg" aria-hidden />,
  danger: <CircleX size={16} className="text-danger-fg" aria-hidden />,
  warning: <TriangleAlert size={16} className="text-warning-fg" aria-hidden />,
  info: <Info size={16} className="text-info-fg" aria-hidden />,
  neutral: <Info size={16} className="text-text-tertiary" aria-hidden />,
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const remove = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), [])
  const dismiss = useCallback((id: number) => setItems((xs) => xs.map((x) => (x.id === id ? { ...x, leaving: true } : x))), [])
  const toast = useCallback(
    (t: ToastInput) => {
      const id = nextId.current++
      setItems((xs) => [...xs.slice(-3), { ...t, id }])
      const d = t.duration ?? (t.tone === 'danger' ? 6000 : 4000)
      if (d > 0) setTimeout(() => dismiss(id), d)
      return id
    },
    [dismiss],
  )
  const api = useMemo(() => ({ toast, dismiss }), [toast, dismiss])

  return (
    <Ctx.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-relevant="additions"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-[70] flex flex-col items-end gap-2 sm:left-auto sm:right-4"
      >
        {items.map((t) => (
          <ToastView key={t.id} t={t} dismiss={dismiss} remove={remove} />
        ))}
      </div>
    </Ctx.Provider>
  )
}

function ToastView({ t, dismiss, remove }: { t: ToastItem; dismiss: (id: number) => void; remove: (id: number) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const tw = t.leaving
      ? gsap.to(el, {
          opacity: 0,
          x: 32,
          height: 0,
          marginTop: -8,
          paddingTop: 0,
          paddingBottom: 0,
          duration: 0.22,
          ease: MOTION.in,
          onComplete: () => remove(t.id),
        })
      : gsap.fromTo(el, { opacity: 0, y: 16, scale: 0.96 }, { opacity: 1, y: 0, scale: 1, duration: 0.32, ease: MOTION.spring, clearProps: 'transform' })
    return () => {
      tw.kill()
    }
  }, [t.leaving, t.id, remove])

  return (
    <div
      ref={ref}
      role={t.tone === 'danger' ? 'alert' : 'status'}
      className="pointer-events-auto flex w-full max-w-sm items-start gap-2.5 overflow-hidden rounded-lg border border-border-default bg-bg-surface p-3 shadow-lg"
    >
      <span className="mt-0.5">{ICON[t.tone ?? 'neutral']}</span>
      <div className="min-w-0 flex-1">
        <p className="text-label text-text-primary">{t.title}</p>
        {t.description && <p className="mt-0.5 break-words text-body-sm text-text-secondary">{t.description}</p>}
        {t.action && (
          <button
            type="button"
            className="focus-ring mt-1.5 rounded-sm text-label text-accent-text hover:underline"
            onClick={() => {
              t.action!.onClick()
              dismiss(t.id)
            }}
          >
            {t.action.label}
          </button>
        )}
      </div>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => dismiss(t.id)}
        className={cn('focus-ring rounded-sm p-0.5 text-text-tertiary hover:text-text-primary')}
      >
        <X size={14} />
      </button>
    </div>
  )
}

/** `const { toast } = useToast(); toast({ title: 'Saved v4', tone: 'success' })` */
// oxlint-disable-next-line react/only-export-components
export function useToast(): ToastApi {
  const c = useContext(Ctx)
  if (!c) throw new Error('useToast must be used inside <ToastProvider>')
  return c
}
