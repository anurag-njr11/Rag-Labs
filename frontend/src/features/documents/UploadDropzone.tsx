import { useId, useRef, useState, type DragEvent } from 'react'
import { TriangleAlert, Upload, X } from 'lucide-react'
import { formatBytes } from '@/api/format'
import { MAX_UPLOAD_BYTES } from '@/api/types'
import { Button, Spinner, cn } from '@/components/ui'
import { ACCEPT_ATTR, ACCEPTED_LABEL, validateFiles, type RejectedFile } from './files'

export interface UploadDropzoneProps {
  /** Called with the valid files (type/size already checked). */
  onFiles: (files: File[]) => void
  uploading?: boolean
  disabled?: boolean
  className?: string
}

/** Drag-and-drop + click-to-browse area. Validates types and sizes against API.md and lists rejected files. */
export function UploadDropzone({ onFiles, uploading, disabled, className }: UploadDropzoneProps) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [rejected, setRejected] = useState<RejectedFile[]>([])
  const hintId = useId()
  const busy = uploading || disabled

  const take = (list: FileList | null) => {
    if (!list || busy) return
    const { accepted, rejected } = validateFiles(Array.from(list))
    setRejected(rejected)
    if (accepted.length) onFiles(accepted)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    take(e.dataTransfer.files)
  }

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div
        onDragOver={(e) => {
          e.preventDefault()
          if (!busy) setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cn(
          'flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-6 py-10 text-center transition-colors',
          over ? 'border-accent-default bg-accent-subtle' : 'border-border-strong bg-bg-subtle',
          busy && 'opacity-70',
        )}
      >
        <span className="flex size-10 items-center justify-center rounded-lg border border-border-default bg-bg-surface text-text-secondary shadow-sm">
          {uploading ? <Spinner size={18} label="Uploading" /> : <Upload size={18} aria-hidden />}
        </span>
        <div>
          <p className="text-label text-text-primary">
            {uploading ? 'Uploading…' : over ? 'Drop to upload' : 'Drag and drop files here'}
          </p>
          <p id={hintId} className="mt-1 text-body-sm text-text-tertiary">
            {ACCEPTED_LABEL} · up to {formatBytes(MAX_UPLOAD_BYTES)} each
          </p>
        </div>
        <Button
          size="sm"
          icon={<Upload size={12} aria-hidden />}
          onClick={() => input.current?.click()}
          disabled={busy}
          aria-describedby={hintId}
        >
          Browse files
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT_ATTR}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            take(e.target.files)
            e.target.value = ''
          }}
        />
      </div>
      {rejected.length > 0 && (
        <div role="alert" className="rounded-lg border border-warning-border bg-warning-bg p-3 text-body">
          <div className="flex items-start gap-2">
            <TriangleAlert size={16} aria-hidden className="mt-0.5 shrink-0 text-warning-fg" />
            <div className="min-w-0 flex-1">
              <p className="text-label text-warning-fg">
                {rejected.length} file{rejected.length === 1 ? '' : 's'} skipped
              </p>
              <ul className="mt-1 flex flex-col gap-0.5 text-body-sm text-text-primary">
                {rejected.map((r) => (
                  <li key={r.name} className="break-words">
                    <span className="font-mono text-mono-sm">{r.name}</span> — {r.reason}
                  </li>
                ))}
              </ul>
            </div>
            <Button variant="ghost" size="sm" iconOnly aria-label="Dismiss" icon={<X size={12} />} onClick={() => setRejected([])} />
          </div>
        </div>
      )}
    </div>
  )
}
