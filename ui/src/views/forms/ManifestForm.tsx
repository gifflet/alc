// ManifestForm.tsx — Structured editor over manifest.yaml (IntelliJ-settings feel).
//
// Edits are applied to a parsed YAML Document and re-serialised, so comments and
// any keys the form does not surface survive untouched. The same `value` string
// backs both this form and the Source editor; the server is the only validator.
import { useState } from 'react'
import { parseDocument } from 'yaml'
import type { Document } from 'yaml'
import { Info, Plus, Trash2 } from 'lucide-react'
import { Field, NumberInput, Select, TextInput } from '../../components/fields'
import { mapKeys, safeDeleteIn, seqStrings } from '../../lib/yamlDoc'
import { CheckListEditor } from './CheckListEditor'
import { StringListEditor } from './StringListEditor'

const KNOBS: { key: string; label: string; def: number }[] = [
  { key: 'default_timeout_s', label: 'Default timeout (s)', def: 1800 },
  { key: 'plan_retries', label: 'Plan retries', def: 2 },
  { key: 'fanout_concurrency', label: 'Fanout concurrency', def: 4 },
  { key: 'max_task_retries', label: 'Max task retries', def: 0 },
]

const DIR_KNOBS: { key: string; label: string; def: string }[] = [
  { key: 'metrics_dir', label: 'Metrics dir', def: '.alc/metrics' },
  { key: 'artifacts_dir', label: 'Artifacts dir', def: '.alc/artifacts' },
  { key: 'signals_dir', label: 'Signals dir', def: '.alc/signals' },
]

const STAGES = ['', 'pre-pmf', 'growth', 'strong-pmf']

const NOTIFY_EVENTS: { key: string; label: string }[] = [
  { key: 'on_task_failed', label: 'On task failed' },
  { key: 'on_loop_stopped', label: 'On loop stopped' },
  { key: 'on_budget_exceeded', label: 'On budget exceeded' },
  { key: 'on_merge_conflict', label: 'On merge conflict' },
]

interface NotifyRow {
  mode: 'none' | 'command' | 'url'
  value: string
}

function readNotifyRow(doc: Document, event: string): NotifyRow {
  const raw = doc.getIn(['notify', event])
  if (raw == null) return { mode: 'none', value: '' }
  if (typeof raw === 'string') return { mode: 'url', value: raw }
  const seq = raw as { toJSON?: () => unknown }
  const v = typeof seq.toJSON === 'function' ? seq.toJSON() : []
  return { mode: 'command', value: Array.isArray(v) ? v.join(' ') : '' }
}

export function ManifestForm({
  value,
  onChange,
}: {
  value: string
  onChange: (raw: string) => void
}) {
  const [newSetName, setNewSetName] = useState('')

  let doc: Document
  try {
    doc = parseDocument(value)
    if (doc.errors.length) throw doc.errors[0]
  } catch {
    return (
      <div className="p-4 text-[length:var(--ui-text-body)] text-error">
        The YAML has a syntax error. Fix it in the Source view to edit fields here.
      </div>
    )
  }

  const update = (mutate: (d: Document) => void) => {
    const next = parseDocument(value)
    mutate(next)
    onChange(String(next))
  }

  const engines = mapKeys(doc.get('engines'))
  const tiers = mapKeys(doc.get('compute_tiers'))
  // Column set: every engine declared, plus any engine referenced by a tier.
  const columns = Array.from(
    new Set([...engines, ...tiers.flatMap((t) => mapKeys(doc.getIn(['compute_tiers', t])))]),
  )
  const defaultEngine = String(doc.get('default_engine') ?? '')
  const strategy = String(doc.get('retry_strategy') ?? 'immediate')
  const stage = String(doc.get('stage') ?? '')
  const checkSetNames = mapKeys(doc.get('check_sets'))
  const quarantinedChecks = seqStrings(doc.get('quarantined_checks'))
  const deliveryMode = String(doc.getIn(['delivery', 'mode']) ?? 'local')
  const deliveryRemote = String(doc.getIn(['delivery', 'remote']) ?? 'origin')
  const deliveryBase = String(doc.getIn(['delivery', 'base']) ?? 'main')

  const cell = (tier: string, engine: string): string => {
    const v = doc.getIn(['compute_tiers', tier, engine])
    return v == null ? '' : String(v)
  }

  const addCheckSet = () => {
    const name = newSetName.trim()
    if (!name || checkSetNames.includes(name)) return
    update((d) => d.setIn(['check_sets', name], [{ name: 'check', command: ['true'] }]))
    setNewSetName('')
  }
  const removeCheckSet = (name: string) => update((d) => d.deleteIn(['check_sets', name]))

  const setNotify = (event: string, row: NotifyRow) =>
    update((d) => {
      if (row.mode === 'none') {
        // Only an explicit "off" clears the key — an empty value while
        // command/url is selected stays that shape (as [] / ''), so picking a
        // mode before typing a value doesn't silently fall back to "none".
        safeDeleteIn(d, ['notify', event])
      } else if (row.mode === 'url') {
        d.setIn(['notify', event], row.value)
      } else {
        d.setIn(['notify', event], row.value.trim() ? row.value.trim().split(/\s+/) : [])
      }
    })

  return (
    <div className="flex flex-col gap-4 overflow-auto p-4">
      <p className="flex items-center gap-1.5 text-[length:var(--ui-text-label)] text-faint">
        <Info className="h-3.5 w-3.5" />
        Form edits known fields only — comments and other keys are preserved.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Default engine">
          <Select
            value={defaultEngine}
            onChange={(v) => update((d) => d.setIn(['default_engine'], v))}
            options={engines.map((e) => ({ value: e, label: e }))}
          />
        </Field>
        <Field label="Retry strategy">
          <Select
            value={strategy}
            onChange={(v) => update((d) => d.setIn(['retry_strategy'], v))}
            options={[
              { value: 'immediate', label: 'immediate' },
              { value: 'deferred', label: 'deferred' },
            ]}
          />
        </Field>
      </div>

      <Field label="Stage">
        <Select
          value={stage}
          onChange={(v) => update((d) => (v === '' ? d.deleteIn(['stage']) : d.setIn(['stage'], v)))}
          options={STAGES.map((s) => ({ value: s, label: s || '(none)' }))}
        />
      </Field>

      <section>
        <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Compute tiers</h3>
        {tiers.length === 0 || columns.length === 0 ? (
          <p className="text-[length:var(--ui-text-body)] text-faint">No tiers declared.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[length:var(--ui-text-body)]">
              <thead>
                <tr className="border-b border-border text-left text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">
                  <th className="px-2 py-1 font-medium">Tier</th>
                  {columns.map((c) => (
                    <th key={c} className="px-2 py-1 font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tiers.map((tier) => (
                  <tr key={tier} className="border-b border-border/15">
                    <td className="px-2 py-1 font-mono text-muted">{tier}</td>
                    {columns.map((engine) => (
                      <td key={engine} className="px-2 py-1">
                        <input
                          value={cell(tier, engine)}
                          onChange={(e) =>
                            update((d) =>
                              d.setIn(['compute_tiers', tier, engine], e.target.value),
                            )
                          }
                          placeholder="model"
                          spellCheck={false}
                          className="w-full rounded-panel border border-border bg-base px-2 py-1 font-mono text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Check sets</h3>
          <div className="flex items-center gap-1">
            <input
              value={newSetName}
              onChange={(e) => setNewSetName(e.target.value)}
              placeholder="set name"
              aria-label="New check set name"
              spellCheck={false}
              className="w-32 rounded-panel border border-border bg-base px-2 py-1 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={addCheckSet}
              disabled={!newSetName.trim()}
              className="flex items-center gap-1 rounded-panel border border-border px-2 py-1 text-[length:var(--ui-text-label)] text-muted hover:bg-hover hover:text-primary disabled:opacity-40"
            >
              <Plus className="h-3 w-3" />
              Add set
            </button>
          </div>
        </div>
        {checkSetNames.length === 0 ? (
          <p className="text-[length:var(--ui-text-body)] text-faint">No check sets.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {checkSetNames.map((name) => (
              <div key={name} className="rounded-panel border border-border p-2">
                <div className="mb-2 flex items-center justify-between">
                  <span className="font-mono text-[length:var(--ui-text-body)] text-muted">{name}</span>
                  <button
                    type="button"
                    aria-label={`Remove set ${name}`}
                    onClick={() => removeCheckSet(name)}
                    className="flex h-6 w-6 items-center justify-center text-faint hover:text-error"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                <CheckListEditor doc={doc} path={['check_sets', name]} update={update} />
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Quarantined checks</h3>
        <StringListEditor
          values={quarantinedChecks}
          onChange={(next) =>
            update((d) => (next.length ? d.setIn(['quarantined_checks'], next) : d.deleteIn(['quarantined_checks'])))
          }
          placeholder="check name"
          emptyLabel="No quarantined checks."
        />
      </section>

      <section>
        <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Notify</h3>
        <div className="flex flex-col gap-2">
          {NOTIFY_EVENTS.map(({ key, label }) => {
            const row = readNotifyRow(doc, key)
            return (
              <div key={key} className="flex items-center gap-2">
                <span className="w-40 shrink-0 text-[length:var(--ui-text-body)] text-muted">{label}</span>
                <select
                  value={row.mode}
                  onChange={(e) => setNotify(key, { ...row, mode: e.target.value as NotifyRow['mode'] })}
                  aria-label={`${label} mode`}
                  className="rounded-panel border border-border bg-base px-2 py-1 text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
                >
                  <option value="none">off</option>
                  <option value="command">command</option>
                  <option value="url">url</option>
                </select>
                {row.mode !== 'none' && (
                  <input
                    value={row.value}
                    onChange={(e) => setNotify(key, { ...row, value: e.target.value })}
                    placeholder={row.mode === 'command' ? 'notify-slack.sh' : 'https://hooks.example.com/…'}
                    aria-label={`${label} value`}
                    spellCheck={false}
                    className="flex-1 rounded-panel border border-border bg-base px-2 py-1 font-mono text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
                  />
                )}
              </div>
            )
          })}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Delivery</h3>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Mode">
            <Select
              value={deliveryMode}
              onChange={(v) => update((d) => d.setIn(['delivery', 'mode'], v))}
              options={[
                { value: 'local', label: 'local' },
                { value: 'push', label: 'push' },
                { value: 'pr', label: 'pr' },
              ]}
            />
          </Field>
          <Field label="Remote">
            <TextInput
              value={deliveryRemote}
              onChange={(v) => update((d) => d.setIn(['delivery', 'remote'], v))}
              mono
            />
          </Field>
          <Field label="Base">
            <TextInput
              value={deliveryBase}
              onChange={(v) => update((d) => d.setIn(['delivery', 'base'], v))}
              mono
            />
          </Field>
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Knobs</h3>
        <div className="grid grid-cols-2 gap-3">
          {KNOBS.map((knob) => {
            const raw = doc.get(knob.key)
            const current = raw == null ? knob.def : Number(raw)
            return (
              <Field key={knob.key} label={knob.label}>
                <NumberInput
                  value={current}
                  onChange={(v) =>
                    update((d) => d.setIn([knob.key], v === '' ? knob.def : v))
                  }
                />
              </Field>
            )
          })}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Directories</h3>
        <div className="grid grid-cols-3 gap-3">
          {DIR_KNOBS.map((knob) => {
            const raw = doc.get(knob.key)
            const current = raw == null ? knob.def : String(raw)
            return (
              <Field key={knob.key} label={knob.label}>
                <TextInput
                  value={current}
                  onChange={(v) => update((d) => d.setIn([knob.key], v === '' ? knob.def : v))}
                  mono
                />
              </Field>
            )
          })}
        </div>
      </section>
    </div>
  )
}
