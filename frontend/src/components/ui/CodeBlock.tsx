import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Check, Copy } from 'lucide-react'
import { Button, type ButtonSize, type ButtonVariant } from './Button'
import { cn } from './cn'

/** Copy text to the clipboard (with a textarea fallback for non-secure contexts). */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      ta.remove()
      return ok
    } catch {
      return false
    }
  }
}

export interface CopyButtonProps {
  text: string
  /** Visible label; omit for icon-only. */
  label?: string
  variant?: ButtonVariant
  size?: ButtonSize
  className?: string
  'aria-label'?: string
}

/** Copy-to-clipboard button; shows a check for 1.5s after copying. */
export function CopyButton({ text, label, variant = 'ghost', size = 'sm', className, ...aria }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)
  const t = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => {
    if (t.current) clearTimeout(t.current)
  }, [])
  const onClick = async () => {
    if (await copyText(text)) {
      setCopied(true)
      if (t.current) clearTimeout(t.current)
      t.current = setTimeout(() => setCopied(false), 1500)
    }
  }
  return (
    <Button
      variant={variant}
      size={size}
      iconOnly={!label}
      aria-label={aria['aria-label'] ?? (label ? undefined : copied ? 'Copied' : 'Copy')}
      onClick={onClick}
      className={className}
      icon={copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
    >
      {label && (copied ? 'Copied' : label)}
      <span className="sr-only" aria-live="polite">{copied ? 'Copied to clipboard' : ''}</span>
    </Button>
  )
}

export interface CodeBlockProps {
  code: string
  /** Title bar label, e.g. "curl" or "Response". */
  title?: ReactNode
  /** Hide the copy button. */
  noCopy?: boolean
  /** Wrap long lines instead of horizontal scroll. */
  wrap?: boolean
  maxHeight?: number | string
  className?: string
}

/** Dark code block (bg-code, mono, text-code) with a copy button top-right. Dark in both themes. */
export function CodeBlock({ code, title, noCopy, wrap, maxHeight, className }: CodeBlockProps) {
  return (
    <div className={cn('group relative overflow-hidden rounded-lg border border-border-default bg-bg-code', className)}>
      {title && (
        <div className="flex h-8 items-center justify-between border-b border-white/10 px-3 text-caption text-text-code/70">
          <span>{title}</span>
        </div>
      )}
      {!noCopy && (
        <CopyButton
          text={code}
          // Without a title bar the button floats over the code; keep it clear of a vertical scrollbar.
          className={cn('absolute text-text-code/70 hover:bg-white/10 hover:text-text-code', title ? 'right-1.5 top-1' : maxHeight ? 'right-4 top-1.5' : 'right-1.5 top-1.5')}
          aria-label="Copy code"
        />
      )}
      <pre
        className={cn('overflow-auto p-3 pr-10 font-mono text-mono text-text-code', wrap ? 'whitespace-pre-wrap break-words' : 'whitespace-pre')}
        style={{ maxHeight }}
        tabIndex={0}
      >
        <code>{code}</code>
      </pre>
    </div>
  )
}
