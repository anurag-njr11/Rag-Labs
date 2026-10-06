import { useProviderModels, useProviders } from '@/api/hooks'
import type { Judge } from '@/api/types'
import { Select } from '@/components/ui'

/**
 * Who grades answers (eval runs with "Also grade answers", and Auto-Optimize sweeps). Default: the version's own
 * Generate model; any model of a configured provider avoids a model grading its own answers.
 */
export function JudgePicker({ value, onChange }: { value: Judge | null; onChange: (j: Judge | null) => void }) {
  const providers = (useProviders().data ?? []).filter((p) => p.available)
  const models = useProviderModels(value?.provider)
  return (
    <div className="flex flex-wrap items-center gap-2" title="Grades answers when answer grading or Auto-Optimize is on. Always run at temperature 0.">
      <span className="text-body-sm text-text-secondary">Judge model</span>
      <Select
        size="sm"
        aria-label="Judge provider"
        value={value?.provider ?? ''}
        options={[{ value: '', label: "Version's own model" }, ...providers.map((p) => ({ value: p.name, label: p.title }))]}
        onChange={(e) => onChange(e.target.value ? { provider: e.target.value, model: '' } : null)}
      />
      {value && (
        <Select
          size="sm"
          aria-label="Judge model"
          value={value.model}
          options={[{ value: '', label: 'Provider default' }, ...(models.data?.models ?? []).map((m) => ({ value: m, label: m }))]}
          onChange={(e) => onChange({ ...value, model: e.target.value })}
          wrapperClassName="max-w-64"
        />
      )}
    </div>
  )
}
