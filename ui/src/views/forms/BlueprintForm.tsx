// BlueprintForm.tsx — Structured editor over a Blueprint's YAML front-matter.
//
// Only the header is parsed/edited; the markdown body is preserved verbatim by
// replaceFrontMatter. Unknown header keys and comments survive the round-trip.
import { parseDocument } from 'yaml'
import type { Document } from 'yaml'
import { Info, Plus, Trash2 } from 'lucide-react'
import { getFrontMatter, replaceFrontMatter } from '../../lib/frontmatter'
import { Field, NumberInput, Select, TextArea, TextInput } from '../../components/fields'

const PERMISSION_MODES = ['', 'default', 'acceptEdits', 'plan', 'bypassPermissions']

interface CheckRow {
  name: string
  mode: 'command' | 'shell'
  value: string
}

function readChecks(doc: Document): CheckRow[] {
  const seq = doc.getIn(['checks']) as { items?: unknown[] } | null
  if (!seq?.items) return []
  return seq.items.map((_, i) => {
    const name = String(doc.getIn(['checks', i, 'name']) ?? '')
    const command = doc.getIn(['checks', i, 'command']) as { toJSON?: () => string[] } | null
    if (command) {
      const argv = typeof command.toJSON === 'function' ? command.toJSON() : []
      return { name, mode: 'command' as const, value: argv.join(' ') }
    }
    const shell = doc.getIn(['checks', i, 'shell'])
    return { name, mode: 'shell' as const, value: shell == null ? '' : String(shell) }
  })
}

export function BlueprintForm({
  value,
  onChange,
  tiers,
  checkSets,
}: {
  value: string
  onChange: (raw: string) => void
  tiers: string[]
  checkSets: string[]
}) {
  const fmText = getFrontMatter(value)
  if (fmText === null) {
    return (
      <div className="p-4 text-[12px] text-error">
        No front-matter found. Edit this file in the Source view.
      </div>
    )
  }
  let doc: Document
  try {
    doc = parseDocument(fmText)
    if (doc.errors.length) throw doc.errors[0]
  } catch {
    return (
      <div className="p-4 text-[12px] text-error">
        The front-matter has a syntax error. Fix it in the Source view to edit fields here.
      </div>
    )
  }

  const update = (mutate: (d: Document) => void) => {
    const next = parseDocument(getFrontMatter(value) ?? '')
    mutate(next)
    const raw = replaceFrontMatter(value, String(next))
    if (raw !== null) onChange(raw)
  }

  const str = (key: string): string => {
    const v = doc.get(key)
    return v == null ? '' : String(v)
  }
  const num = (key: string): number | '' => {
    const v = doc.get(key)
    return v == null ? '' : Number(v)
  }

  const tierOptions = Array.from(new Set([str('compute_tier') || 'standard', ...tiers]))
  const checks = readChecks(doc)

  const setCheck = (i: number, row: CheckRow) => {
    update((d) => {
      d.setIn(['checks', i, 'name'], row.name)
      if (row.mode === 'command') {
        d.deleteIn(['checks', i, 'shell'])
        const argv = row.value.trim() ? row.value.trim().split(/\s+/) : ['true']
        d.setIn(['checks', i, 'command'], argv)
      } else {
        d.deleteIn(['checks', i, 'command'])
        d.setIn(['checks', i, 'shell'], row.value)
      }
    })
  }

  const addCheck = () =>
    update((d) => {
      const seq = d.getIn(['checks']) as { add?: (v: unknown) => void } | null
      const item = { name: 'check', command: ['true'] }
      if (seq?.add) seq.add(item)
      else d.setIn(['checks'], [item])
    })

  const removeCheck = (i: number) => update((d) => d.deleteIn(['checks', i]))

  return (
    <div className="flex flex-col gap-4 overflow-auto p-4">
      <p className="flex items-center gap-1.5 text-[11px] text-faint">
        <Info className="h-3.5 w-3.5" />
        Form edits the front-matter only — the workflow body, comments and other keys are preserved.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Name">
          <TextInput value={str('name')} onChange={(v) => update((d) => d.setIn(['name'], v))} />
        </Field>
        <Field label="Compute tier">
          <Select
            value={str('compute_tier') || 'standard'}
            onChange={(v) => update((d) => d.setIn(['compute_tier'], v))}
            options={tierOptions.map((t) => ({ value: t, label: t }))}
          />
        </Field>
      </div>

      <Field label="Purpose">
        <TextArea value={str('purpose')} onChange={(v) => update((d) => d.setIn(['purpose'], v))} />
      </Field>

      <div className="grid grid-cols-3 gap-3">
        <Field label="Max repairs">
          <NumberInput
            value={num('max_repairs')}
            onChange={(v) =>
              update((d) => (v === '' ? d.deleteIn(['max_repairs']) : d.setIn(['max_repairs'], v)))
            }
          />
        </Field>
        <Field label="Timeout (s)">
          <NumberInput
            value={num('timeout_s')}
            onChange={(v) =>
              update((d) => (v === '' ? d.deleteIn(['timeout_s']) : d.setIn(['timeout_s'], v)))
            }
          />
        </Field>
        <Field label="Permission mode">
          <Select
            value={str('permission_mode')}
            onChange={(v) =>
              update((d) => (v === '' ? d.deleteIn(['permission_mode']) : d.setIn(['permission_mode'], v)))
            }
            options={PERMISSION_MODES.map((m) => ({ value: m, label: m || '(engine default)' }))}
          />
        </Field>
      </div>

      <Field label="Check set">
        <Select
          value={str('check_set')}
          onChange={(v) =>
            update((d) => (v === '' ? d.deleteIn(['check_set']) : d.setIn(['check_set'], v)))
          }
          options={[{ value: '', label: '(none)' }, ...checkSets.map((c) => ({ value: c, label: c }))]}
        />
      </Field>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[11px] uppercase tracking-wide text-faint">Checks</h3>
          <button
            type="button"
            onClick={addCheck}
            className="flex items-center gap-1 rounded-panel border border-border px-2 py-1 text-[11px] text-muted hover:bg-hover hover:text-primary"
          >
            <Plus className="h-3 w-3" />
            Add check
          </button>
        </div>
        {checks.length === 0 ? (
          <p className="text-[12px] text-faint">No checks.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {checks.map((row, i) => (
              <div key={i} className="flex items-center gap-2">
                <input
                  value={row.name}
                  onChange={(e) => setCheck(i, { ...row, name: e.target.value })}
                  placeholder="name"
                  spellCheck={false}
                  className="w-28 rounded-panel border border-border bg-base px-2 py-1 text-[12px] text-primary outline-none focus:border-accent"
                />
                <select
                  value={row.mode}
                  onChange={(e) => setCheck(i, { ...row, mode: e.target.value as CheckRow['mode'] })}
                  className="rounded-panel border border-border bg-base px-2 py-1 text-[12px] text-primary outline-none focus:border-accent"
                >
                  <option value="command">command</option>
                  <option value="shell">shell</option>
                </select>
                <input
                  value={row.value}
                  onChange={(e) => setCheck(i, { ...row, value: e.target.value })}
                  placeholder={row.mode === 'command' ? 'pytest -q' : 'test -z "$(git diff)"'}
                  spellCheck={false}
                  className="flex-1 rounded-panel border border-border bg-base px-2 py-1 font-mono text-[12px] text-primary outline-none focus:border-accent"
                />
                <button
                  type="button"
                  aria-label={`Remove ${row.name}`}
                  onClick={() => removeCheck(i)}
                  className="flex h-6 w-6 items-center justify-center text-faint hover:text-error"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
