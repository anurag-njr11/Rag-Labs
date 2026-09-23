import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { Button } from './Button'
import { cn } from './cn'

export interface DialogProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  /** Footer actions, right-aligned. */
  footer?: ReactNode
  /** Max width: sm 400 · md 520 (default) · lg 720 · xl 960. */
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  /** Close when clicking the backdrop (default true). */
  dismissible?: boolean
}

const widths = { sm: 'max-w-[400px]', md: 'max-w-[520px]', lg: 'max-w-[720px]', xl: 'max-w-[960px]' }

/** Modal built on native <dialog> (focus trap, Esc, inert background). Radius xl, shadow-lg. */
export function Dialog({ open, onClose, title, description, children, footer, size = 'md', className, dismissible = true }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const descId = useId()

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    else if (!open && d.open) d.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={(e) => {
        if (dismissible && e.target === ref.current) onClose()
      }}
      className={cn(
        'm-auto w-[calc(100vw-32px)] rounded-xl border border-border-default bg-bg-surface p-0 text-text-primary shadow-lg',
        'backdrop:bg-black/40 backdrop:backdrop-blur-[1px]',
        widths[size],
        className,
      )}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <div className="flex items-start justify-between gap-4 px-5 pt-5">
            <div className="min-w-0">
              <h2 id={titleId} className="text-title">{title}</h2>
              {description && <p id={descId} className="mt-1 text-body text-text-secondary">{description}</p>}
            </div>
            <Button variant="ghost" size="sm" iconOnly aria-label="Close" onClick={onClose} icon={<X size={14} />} />
          </div>
          {children != null && children !== false ? (
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          ) : (
            <div className="h-4" aria-hidden />
          )}
          {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-border-default px-5 py-3">{footer}</div>}
        </div>
      )}
    </dialog>
  )
}
