import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { ButtonLink, Stepper } from '@/components/ui'

const WIZARD_STEPS = [{ label: 'Name' }, { label: 'Documents' }, { label: 'Configure' }, { label: 'Build' }]

/** White header band with the title + stepper, centered 880px column. */
export function WizardHeader({
  step, onStepClick, exitTo, title,
}: { step: number; onStepClick?: (i: number) => void; exitTo: string; title: string }) {
  return (
    <div className="border-b border-border-default bg-bg-surface">
      <div className="mx-auto flex w-full max-w-[880px] flex-col gap-4 px-4 py-5 sm:px-6">
        <div className="flex items-center justify-between gap-3">
          <h1 className="min-w-0 truncate text-title text-text-primary">{title}</h1>
          <ButtonLink to={exitTo} variant="ghost" size="sm" icon={<X size={12} aria-hidden />}>
            {exitTo === '/' ? 'Cancel' : 'Exit wizard'}
          </ButtonLink>
        </div>
        <Stepper steps={WIZARD_STEPS} current={step} onStepClick={onStepClick} />
      </div>
    </div>
  )
}

/** Page body column. Bottom padding leaves room for the sticky footer. `wide` gives the
 *  Configure step room for the stage nav + parameter cards. */
export function WizardBody({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className={`mx-auto flex w-full ${wide ? 'max-w-[1200px]' : 'max-w-[880px]'} flex-1 flex-col gap-6 px-4 pb-28 pt-8 sm:px-6`}>
      {children}
    </div>
  )
}

/** Sticky footer: hint/"Step n of 4" on the left, actions on the right. */
export function WizardFooter({ step, hint, wide, children }: { step: number; hint?: ReactNode; wide?: boolean; children: ReactNode }) {
  return (
    <div className="sticky bottom-0 z-20 border-t border-border-default bg-bg-surface shadow-[0_-1px_3px_rgb(16_16_19/0.06),0_-4px_12px_rgb(16_16_19/0.06)] pb-[env(safe-area-inset-bottom)]">
      <div className={`mx-auto flex min-h-16 w-full ${wide ? 'max-w-[1200px]' : 'max-w-[880px]'} flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3 sm:px-6`}>
        <p className="min-w-0 text-body-sm text-text-tertiary" aria-live="polite">
          {hint ?? `Step ${step + 1} of ${WIZARD_STEPS.length}`}
        </p>
        <div className="ml-auto flex items-center gap-2">{children}</div>
      </div>
    </div>
  )
}

/** Step section title. */
export function StepIntro({ title, description }: { title: string; description: ReactNode }) {
  return (
    <div>
      <h2 className="text-display text-text-primary">{title}</h2>
      <p className="mt-1 text-body text-text-secondary">{description}</p>
    </div>
  )
}
