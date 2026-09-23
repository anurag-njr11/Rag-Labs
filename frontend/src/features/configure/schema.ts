import type {
  Change, Effect, JSONSchema, JSONSchemaProperty, NodeConfig, NodeType, PipelineConfig, PipelineFieldError, Slot, SlotCatalog,
} from '@/api/types'
import { SLOTS } from '@/api/types'

/** How a schema property is rendered. Derived purely from the JSON Schema. */
export type FieldKind = 'enum' | 'slider' | 'number' | 'boolean' | 'list' | 'textarea' | 'combobox' | 'text' | 'json'

export interface ResolvedField {
  name: string
  /** The property as sent (title/description/advanced/widget/... live here). */
  prop: JSONSchemaProperty
  /** The value schema after following $ref / allOf / nullable anyOf. */
  base: JSONSchemaProperty
  kind: FieldKind
  nullable: boolean
  label: string
  help?: string
  advanced: boolean
  enumValues: unknown[]
  enumLabels?: Record<string, string>
}

const refName = (ref: string) => ref.split('/').pop() ?? ref

/** Follow `$ref` (into `$defs`) and single-member `allOf`, merging the outer keys over the target. */
function deref(p: JSONSchemaProperty, root: JSONSchema, depth = 0): JSONSchemaProperty {
  if (depth > 8) return p
  if (p.$ref) {
    const target = root.$defs?.[refName(p.$ref)] ?? {}
    const { $ref: _r, ...rest } = p
    void _r
    return deref({ ...target, ...rest }, root, depth + 1)
  }
  if (p.allOf && p.allOf.length === 1) {
    const { allOf, ...rest } = p
    return deref({ ...deref(allOf[0], root, depth + 1), ...rest }, root, depth + 1)
  }
  return p
}

const isNullSchema = (s: JSONSchemaProperty) => s.type === 'null' || (s.enum?.length === 1 && s.enum[0] === null)

export function humanizeName(name: string): string {
  const s = name.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** Resolve one property of a node schema into a renderable field description. */
export function resolveField(name: string, raw: JSONSchemaProperty, root: JSONSchema): ResolvedField {
  const prop = deref(raw, root)
  let base: JSONSchemaProperty = prop
  let nullable = false
  if (prop.anyOf?.length) {
    const branches = prop.anyOf.map((b) => deref(b, root))
    nullable = branches.some(isNullSchema)
    const nonNull = branches.filter((b) => !isNullSchema(b))
    if (nonNull.length === 1) base = { ...nonNull[0] }
    else if (nonNull.length > 1 && nonNull.every((b) => b.enum || b.const !== undefined)) {
      // anyOf of enums/consts → one enum
      base = { type: nonNull[0].type, enum: nonNull.flatMap((b) => b.enum ?? [b.const]) }
    } else base = { ...prop }
  }
  if (Array.isArray(base.type)) {
    const types = (base.type as string[]).filter((t) => t !== 'null')
    nullable = nullable || types.length !== (base.type as string[]).length
    base = { ...base, type: types[0] as JSONSchemaProperty['type'] }
  }
  if (base.const !== undefined && !base.enum) base = { ...base, enum: [base.const] }
  let enumValues = (base.enum ?? []).filter((v) => v !== null)
  if (prop.enum && !base.enum) enumValues = prop.enum.filter((v) => v !== null)
  if ((base.enum ?? prop.enum ?? []).includes(null)) nullable = true

  const t = base.type
  let kind: FieldKind
  if (enumValues.length) kind = 'enum'
  else if (prop.options_from) kind = 'combobox'
  else if (t === 'boolean') kind = 'boolean'
  else if (t === 'integer' || t === 'number') {
    kind = typeof base.minimum === 'number' && typeof base.maximum === 'number' ? 'slider' : 'number'
  } else if (t === 'array' && (!base.items || deref(base.items, root).type === 'string' || !deref(base.items, root).type)) kind = 'list'
  else if (t === 'string' || (!t && nullable)) kind = prop.widget === 'textarea' ? 'textarea' : 'text'
  else kind = 'json'

  return {
    name,
    prop,
    base,
    kind,
    nullable,
    label: prop.title || humanizeName(name),
    help: prop.description,
    advanced: !!prop.advanced,
    enumValues,
    enumLabels: prop.enum_labels ?? base.enum_labels,
  }
}

export function resolveFields(schema: JSONSchema): ResolvedField[] {
  return Object.entries(schema.properties ?? {})
    .filter(([name]) => name !== 'type')
    .map(([name, p]) => resolveField(name, p, schema))
}

export const fieldEffect = (node: NodeType | undefined, slot: SlotCatalog | undefined, field: string): Effect =>
  node?.effects[field] ?? slot?.effect ?? 'rebuild'

/** Vector-store exactness for a node type given the current params (null when unknown). */
export function isExact(node: NodeType, cfg: NodeConfig | undefined): boolean | null {
  if (node.exact !== null && node.exact !== undefined) return node.exact
  if (!node.exact_when) return null
  const values = cfg && cfg.type === node.type ? cfg : node.defaults
  return Object.entries(node.exact_when).every(([k, allowed]) => allowed.some((a) => deepEqual(a, values[k] ?? node.defaults[k])))
}

export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (typeof a !== typeof b || a === null || b === null || typeof a !== 'object') return false
  if (Array.isArray(a) !== Array.isArray(b)) return false
  if (Array.isArray(a)) {
    const bb = b as unknown[]
    return a.length === bb.length && a.every((v, i) => deepEqual(v, bb[i]))
  }
  const ao = a as Record<string, unknown>
  const bo = b as Record<string, unknown>
  const keys = new Set([...Object.keys(ao), ...Object.keys(bo)])
  for (const k of keys) if (!deepEqual(ao[k], bo[k])) return false
  return true
}

/** Local (client-side) diff — used for nav dots and as a fallback until the server estimate returns. */
export function localChanges(base: PipelineConfig | undefined, next: PipelineConfig, catalog: SlotCatalog[] | undefined): Change[] {
  if (!base) return []
  const out: Change[] = []
  for (const slot of SLOTS) {
    const a = base[slot] ?? { type: '' }
    const b = next[slot] ?? { type: '' }
    const sc = catalog?.find((s) => s.slot === slot)
    if (a.type !== b.type) {
      out.push({ slot, field: 'type', before: a.type, after: b.type, effect: sc?.effect ?? 'rebuild' })
      continue
    }
    const nt = sc?.types.find((t) => t.type === b.type)
    const keys = new Set([...Object.keys(a), ...Object.keys(b)])
    keys.delete('type')
    for (const k of keys) {
      if (!deepEqual(a[k], b[k])) out.push({ slot, field: k, before: a[k], after: b[k], effect: fieldEffect(nt, sc, k) })
    }
  }
  return out
}

export function errorsFor(errors: PipelineFieldError[] | undefined, slot: Slot) {
  const fieldErrors: Record<string, string> = {}
  const general: string[] = []
  for (const e of errors ?? []) {
    if (e.slot !== slot) continue
    const f = e.field?.split('.')[0]
    const message = e.message.replace(/^Value error, /i, '')
    if (f && f !== 'type') fieldErrors[f] = fieldErrors[f] ? `${fieldErrors[f]} ${message}` : message
    else general.push(message)
  }
  return { fieldErrors, general }
}

/** Show a list value's escapes (so "\n\n" is visible and editable). */
export const escapeStr = (s: string) => JSON.stringify(s).slice(1, -1)
export function unescapeStr(s: string): string {
  let q = ''
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '\\' && i + 1 < s.length) {
      q += s[i] + s[i + 1]
      i++
    } else if (s[i] === '"') q += '\\"'
    else if (s[i] === '\\') q += '\\\\'
    else q += s[i]
  }
  try {
    return JSON.parse(`"${q}"`) as string
  } catch {
    return s
  }
}
