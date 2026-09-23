import { useMemo, useState, type ComponentProps } from 'react'
import { Plus, X } from 'lucide-react'
import { fillOptionsFrom, useOptionsFrom } from '@/api/hooks'
import type { NodeConfig, NodeType, SlotCatalog } from '@/api/types'
import {
  Button, Combobox, Disclosure, EffectBadge, Field, Input, Select, Slider, Switch, Textarea, cn,
} from '@/components/ui'
import { escapeStr, fieldEffect, resolveFields, unescapeStr, type ResolvedField } from './schema'

export interface SchemaFormProps {
  node: NodeType
  slot?: SlotCatalog
  value: NodeConfig
  onChange: (next: NodeConfig) => void
  /** field name → error message */
  errors?: Record<string, string>
  /** Fields that differ from the saved version (shows a small "edited" dot). */
  changed?: Set<string>
  /** Prefix for control ids (unique per stage). */
  idPrefix: string
}

/**
 * Renders a node type's params purely from its JSON Schema — no node-specific code.
 * Advanced fields go under an "Advanced" disclosure.
 */
export function SchemaForm({ node, slot, value, onChange, errors, changed, idPrefix }: SchemaFormProps) {
  const fields = useMemo(() => resolveFields(node.schema), [node.schema])
  const basic = fields.filter((f) => !f.advanced)
  const advanced = fields.filter((f) => f.advanced)
  const advancedHasError = advanced.some((f) => errors?.[f.name])
  const advancedChanged = advanced.filter((f) => changed?.has(f.name)).length
  const [advOpen, setAdvOpen] = useState(false)

  if (!fields.length) {
    return <p className="text-body-sm text-text-tertiary">No parameters for this option.</p>
  }

  const set = (name: string, v: unknown) => onChange({ ...value, [name]: v })
  const render = (f: ResolvedField) => (
    <SchemaField
      key={`${node.type}-${f.name}`}
      field={f}
      node={node}
      slot={slot}
      nodeValue={value}
      value={value[f.name] === undefined ? node.defaults[f.name] : value[f.name]}
      onChange={(v) => set(f.name, v)}
      error={errors?.[f.name]}
      changed={changed?.has(f.name)}
      id={`${idPrefix}-${f.name}`}
    />
  )

  return (
    <div className="flex flex-col gap-5">
      {basic.length > 0 && <div className="grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-2">{basic.map(render)}</div>}
      {advanced.length > 0 && (
        <Disclosure
          label="Advanced"
          hint={
            <>
              {advanced.length} more
              {advancedChanged > 0 && ` · ${advancedChanged} edited`}
              {advancedHasError && <span className="text-danger-fg"> · has errors</span>}
            </>
          }
          open={advOpen || advancedHasError}
          onOpenChange={setAdvOpen}
        >
          <div className="grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-2">{advanced.map(render)}</div>
        </Disclosure>
      )}
    </div>
  )
}

interface SchemaFieldProps {
  field: ResolvedField
  node: NodeType
  slot?: SlotCatalog
  nodeValue: NodeConfig
  value: unknown
  onChange: (v: unknown) => void
  error?: string
  changed?: boolean
  id: string
}

const wide = (f: ResolvedField) => f.kind === 'list' || f.kind === 'textarea' || f.kind === 'json'

/** Decimal step for `number` sliders: a round power of ten ≈ 1/100 of the range. */
function niceStep(min: number, max: number) {
  const span = max - min
  if (!(span > 0)) return 0.01
  return Math.pow(10, Math.floor(Math.log10(span / 100)))
}

function SchemaField({ field: f, node, slot, nodeValue, value, onChange, error, changed, id }: SchemaFieldProps) {
  const effect = fieldEffect(node, slot, f.name)
  const label = (
    <span className="inline-flex items-center gap-1.5">
      {f.label}
      {changed && (
        <span
          title="Edited — differs from the saved version"
          className={cn('size-1.5 rounded-full', effect === 'rebuild' ? 'bg-rebuild-fg' : 'bg-instant-fg')}
        >
          <span className="sr-only">(edited)</span>
        </span>
      )}
    </span>
  )
  const badge = <EffectBadge effect={effect} />
  const common = { label, badge, help: f.help, error, id, className: wide(f) ? 'md:col-span-2' : undefined }

  switch (f.kind) {
    case 'boolean':
      return (
        <Field {...common} inline>
          {(p) => <Switch id={p.id} aria-describedby={p.describedBy} checked={!!value} onChange={onChange} />}
        </Field>
      )
    case 'enum': {
      const opts = f.enumValues.map((v) => ({ value: String(v), label: f.enumLabels?.[String(v)] ?? String(v) }))
      if (f.nullable) opts.unshift({ value: '', label: 'None' })
      const cur = value === null || value === undefined ? '' : String(value)
      if (cur && !opts.some((o) => o.value === cur)) opts.push({ value: cur, label: `${cur} (not in list)` })
      return (
        <Field {...common}>
          {(p) => (
            <Select
              id={p.id}
              aria-describedby={p.describedBy}
              invalid={p.invalid}
              options={opts}
              value={cur}
              onChange={(e) => {
                const s = e.target.value
                onChange(s === '' && f.nullable ? null : (f.enumValues.find((v) => String(v) === s) ?? s))
              }}
            />
          )}
        </Field>
      )
    }
    case 'slider': {
      const min = f.base.minimum as number
      const max = f.base.maximum as number
      const integer = f.base.type === 'integer'
      const num = typeof value === 'number' ? value : Number(value ?? f.base.default ?? min)
      return (
        <Field {...common}>
          {(p) => (
            <Slider
              id={p.id}
              aria-describedby={p.describedBy}
              invalid={p.invalid}
              min={min}
              max={max}
              integer={integer}
              step={integer ? 1 : niceStep(min, max)}
              value={Number.isFinite(num) ? num : min}
              onChange={onChange}
            />
          )}
        </Field>
      )
    }
    case 'number':
      return (
        <Field {...common}>
          {(p) => (
            <Input
              id={p.id}
              aria-describedby={p.describedBy}
              invalid={p.invalid}
              type="number"
              mono
              min={f.base.minimum}
              max={f.base.maximum}
              step={f.base.type === 'integer' ? 1 : 'any'}
              value={value === null || value === undefined ? '' : String(value)}
              onChange={(e) => {
                const s = e.target.value
                if (s === '') return onChange(f.nullable ? null : s)
                const n = Number(s)
                onChange(Number.isNaN(n) ? s : f.base.type === 'integer' ? Math.round(n) : n)
              }}
            />
          )}
        </Field>
      )
    case 'combobox':
      return <ComboField common={common} field={f} node={node} nodeValue={nodeValue} value={value} onChange={onChange} />
    case 'list':
      return (
        <Field {...common}>
          {(p) => <ListEditor id={p.id} describedBy={p.describedBy} invalid={p.invalid} label={f.label} value={value} onChange={onChange} />}
        </Field>
      )
    case 'textarea':
      return (
        <Field {...common}>
          {(p) => (
            <Textarea
              id={p.id}
              aria-describedby={p.describedBy}
              invalid={p.invalid}
              mono
              rows={6}
              value={value === null || value === undefined ? '' : String(value)}
              onChange={(e) => onChange(e.target.value === '' && f.nullable ? null : e.target.value)}
            />
          )}
        </Field>
      )
    case 'json':
      return <JsonField common={common} value={value} onChange={onChange} />
    default:
      return (
        <Field {...common}>
          {(p) => (
            <Input
              id={p.id}
              aria-describedby={p.describedBy}
              invalid={p.invalid}
              value={value === null || value === undefined ? '' : String(value)}
              placeholder={f.nullable ? 'Empty = none' : undefined}
              onChange={(e) => onChange(e.target.value === '' && f.nullable ? null : e.target.value)}
            />
          )}
        </Field>
      )
  }
}

type Common = Omit<ComponentProps<typeof Field>, 'children'>

function ComboField({
  common, field: f, node, nodeValue, value, onChange,
}: { common: Common; field: ResolvedField; node: NodeType; nodeValue: NodeConfig; value: unknown; onChange: (v: unknown) => void }) {
  const url = fillOptionsFrom(f.prop.options_from as string, { ...nodeValue, type: node.type })
  const q = useOptionsFrom(url)
  const options = q.data?.models ?? []
  const str = value === null || value === undefined ? '' : String(value)
  return (
    <Field {...common}>
      {(p) => (
        <Combobox
          id={p.id}
          aria-describedby={p.describedBy}
          invalid={p.invalid}
          mono
          value={str}
          options={options}
          loading={q.isFetching}
          placeholder={options[0] ? `Default · ${options[0]}` : 'Provider default'}
          onChange={(s) => onChange(s === '' && f.nullable ? null : s)}
        />
      )}
    </Field>
  )
}

/** Editable list of strings. Escapes (\n, \t) are shown literally so whitespace separators stay visible. */
function ListEditor({
  id, describedBy, invalid, label, value, onChange,
}: { id: string; describedBy?: string; invalid: boolean; label: string; value: unknown; onChange: (v: unknown) => void }) {
  const items = Array.isArray(value) ? value.map((v) => String(v)) : []
  const update = (next: string[]) => onChange(next)
  return (
    <div className="flex flex-col gap-1.5" role="group" aria-describedby={describedBy}>
      {items.length === 0 && <p className="text-body-sm text-text-tertiary">Empty list.</p>}
      {items.map((it, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-5 shrink-0 text-right font-mono text-mono-sm text-text-tertiary">{i + 1}</span>
          <ListRow
            id={i === 0 ? id : undefined}
            label={`${label} item ${i + 1}`}
            invalid={invalid}
            value={it}
            onChange={(v) => update(items.map((x, j) => (j === i ? v : x)))}
          />
          <Button
            variant="ghost"
            size="sm"
            iconOnly
            icon={<X size={14} aria-hidden />}
            aria-label={`Remove ${label} item ${i + 1}`}
            onClick={() => update(items.filter((_, j) => j !== i))}
          />
        </div>
      ))}
      <div className="flex items-center gap-3 pl-7">
        <Button variant="ghost" size="sm" icon={<Plus size={14} aria-hidden />} onClick={() => update([...items, ''])}>
          Add item
        </Button>
        <span className="text-body-sm text-text-tertiary">
          Use <code className="font-mono">\n</code> for a newline.
        </span>
      </div>
    </div>
  )
}

function ListRow({ id, label, invalid, value, onChange }: { id?: string; label: string; invalid: boolean; value: string; onChange: (v: string) => void }) {
  /** Raw text while focused, so typing a backslash escape doesn't get re-escaped mid-edit. */
  const [draft, setDraft] = useState<string | null>(null)
  return (
    <Input
      id={id}
      aria-label={label}
      invalid={invalid}
      mono
      size="sm"
      wrapperClassName="flex-1"
      value={draft ?? escapeStr(value)}
      placeholder='"" (empty string)'
      suffix={/^ +$/.test(value) ? (value.length === 1 ? 'space' : `${value.length} spaces`) : undefined}
      onChange={(e) => {
        setDraft(e.target.value)
        onChange(unescapeStr(e.target.value))
      }}
      onBlur={() => setDraft(null)}
    />
  )
}

/** Fallback for shapes the form doesn't know: raw JSON. */
function JsonField({ common, value, onChange }: { common: Common; value: unknown; onChange: (v: unknown) => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [bad, setBad] = useState(false)
  return (
    <Field {...common} error={common.error ?? (bad ? 'Not valid JSON' : undefined)}>
      {(p) => (
        <Textarea
          id={p.id}
          aria-describedby={p.describedBy}
          invalid={p.invalid}
          mono
          rows={4}
          value={draft ?? JSON.stringify(value ?? null, null, 2)}
          onChange={(e) => {
            setDraft(e.target.value)
            try {
              onChange(JSON.parse(e.target.value))
              setBad(false)
            } catch {
              setBad(true)
            }
          }}
          onBlur={() => !bad && setDraft(null)}
        />
      )}
    </Field>
  )
}
