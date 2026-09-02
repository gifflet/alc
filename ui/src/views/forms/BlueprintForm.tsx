// BlueprintForm.tsx — Structured editor over a Blueprint's YAML front-matter.
//
// Only the header is parsed/edited; the markdown body is preserved verbatim by
// replaceFrontMatter. Unknown header keys and comments survive the round-trip.
import { parseDocument } from 'yaml'
import type { Document } from 'yaml'
import { Info } from 'lucide-react'
import { getFrontMatter, replaceFrontMatter } from '../../lib/frontmatter'
import { seqStrings } from '../../lib/yamlDoc'
import { Field, NumberInput, Select, TextArea, TextInput } from '../../components/fields'
import { CheckListEditor } from './CheckListEditor'
import { StringListEditor } from './StringListEditor'

const PERMISSION_MODES = ['', 'default', 'acceptEdits', 'plan', 'bypassPermissions']
const ARCHETYPES = ['', 'prototyper', 'builder', 'sweeper', 'grower', 'maintainer']

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
      <div className="p-4 text-[length:var(--ui-text-body)] text-error">
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
      <div className="p-4 text-[length:var(--ui-text-body)] text-error">
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
  const setOrClear = (key: string, v: string) =>
    update((d) => (v === '' ? d.deleteIn([key]) : d.setIn([key], v)))

  const tierOptions = Array.from(new Set([str('compute_tier') || 'standard', ...tiers]))
  const protect = seqStrings(doc.get('protect'))

  return (
    <div className="flex flex-col gap-4 overflow-auto p-4">
      <p className="flex items-center gap-1.5 text-[length:var(--ui-text-label)] text-faint">
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
        {/* A stored value the manifest does not declare must stay VISIBLE — the
            select used to render it as "(none)", silently misrepresenting the
            file and rewriting it on save (finding 35). The invalid value gets
            its own labelled option instead. */}
        <Select
          value={str('check_set')}
          onChange={(v) =>
            update((d) => (v === '' ? d.deleteIn(['check_set']) : d.setIn(['check_set'], v)))
          }
          options={[
            { value: '', label: '(none)' },
            ...(str('check_set') && !checkSets.includes(str('check_set'))
              ? [{ value: str('check_set'), label: `${str('check_set')} (not declared!)` }]
              : []),
            ...checkSets.map((c) => ({ value: c, label: c })),
          ]}
        />
      </Field>

      <section>
        <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Team-metaphor / lifecycle</h3>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Archetype">
            <Select
              value={str('archetype')}
              onChange={(v) => setOrClear('archetype', v)}
              options={ARCHETYPES.map((a) => ({ value: a, label: a || '(none)' }))}
            />
          </Field>
          <Field label="Mode">
            <Select
              value={str('mode')}
              onChange={(v) => setOrClear('mode', v)}
              options={[
                { value: '', label: '(none)' },
                { value: 'spike', label: 'spike' },
              ]}
            />
          </Field>
          <Field label="Expect">
            <Select
              value={str('expect')}
              onChange={(v) => setOrClear('expect', v)}
              options={[
                { value: '', label: '(none)' },
                { value: 'shrink', label: 'shrink' },
              ]}
            />
          </Field>
        </div>
      </section>

      <Field label="Capture">
        <TextInput
          value={str('capture')}
          onChange={(v) => setOrClear('capture', v)}
          placeholder="scripts/capture.sh"
          mono
        />
      </Field>

      <section>
        <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Protected paths</h3>
        <StringListEditor
          values={protect}
          onChange={(next) =>
            update((d) => (next.length ? d.setIn(['protect'], next) : d.deleteIn(['protect'])))
          }
          placeholder="src/**/*.py"
          emptyLabel="No protected globs."
        />
      </section>

      <section>
        <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Checks</h3>
        <CheckListEditor doc={doc} path={['checks']} update={update} />
      </section>
    </div>
  )
}
