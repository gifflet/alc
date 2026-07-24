// LoopForm.tsx — Structured editor over a Loop's YAML (.alc/loops/<name>.yaml).
//
// Edits are applied to a parsed YAML Document and re-serialised, so comments and
// any keys the form does not surface survive untouched — same contract as
// ManifestForm. `replenish` is optional (absent -> Mode B, drain-only); its
// `kind` selects the dispatch target (models.Replenish), including the
// `signals`/`regression` kinds later phases added.
import { parseDocument } from 'yaml'
import type { Document } from 'yaml'
import { Info } from 'lucide-react'
import { Checkbox, Field, NumberInput, Select, TextInput } from '../../components/fields'
import { safeDeleteIn } from '../../lib/yamlDoc'

const REPLENISH_KINDS = ['specialist', 'conduct', 'flow', 'plan', 'signals', 'regression']
const BUDGET_UNITS = ['engine_calls', 'usd', 'tokens']

export function LoopForm({ value, onChange }: { value: string; onChange: (raw: string) => void }) {
  let doc: Document
  try {
    doc = parseDocument(value)
    if (doc.errors.length) throw doc.errors[0]
  } catch {
    return (
      <div className="p-4 text-[12px] text-error">
        The YAML has a syntax error. Fix it in the Source view to edit fields here.
      </div>
    )
  }

  const update = (mutate: (d: Document) => void) => {
    const next = parseDocument(value)
    mutate(next)
    onChange(String(next))
  }

  const name = String(doc.get('name') ?? '')
  const hasReplenish = doc.hasIn(['replenish'])
  const replenishKind = String(doc.getIn(['replenish', 'kind']) ?? 'conduct')
  const replenishRef = String(doc.getIn(['replenish', 'ref']) ?? '')
  const replenishTask = String(doc.getIn(['replenish', 'task']) ?? '')

  const maxCyclesRaw = doc.getIn(['stop', 'max_cycles'])
  const maxCycles = maxCyclesRaw == null ? '' : Number(maxCyclesRaw)
  const onNoNewWorkRaw = doc.getIn(['stop', 'on_no_new_work'])
  const onNoNewWork = onNoNewWorkRaw == null ? true : Boolean(onNoNewWorkRaw)
  const hasBudget = doc.hasIn(['stop', 'budget'])
  const budgetUnit = String(doc.getIn(['stop', 'budget', 'unit']) ?? 'usd')
  const budgetMax = Number(doc.getIn(['stop', 'budget', 'max']) ?? 1)

  const setReplenishEnabled = (on: boolean) =>
    update((d) => {
      if (on) d.setIn(['replenish'], { kind: 'conduct', task: '' })
      else safeDeleteIn(d, ['replenish'])
    })

  const setBudgetEnabled = (on: boolean) =>
    update((d) => {
      if (on) d.setIn(['stop', 'budget'], { unit: 'usd', max: 1 })
      else safeDeleteIn(d, ['stop', 'budget'])
    })

  return (
    <div className="flex flex-col gap-4 overflow-auto p-4">
      <p className="flex items-center gap-1.5 text-[11px] text-faint">
        <Info className="h-3.5 w-3.5" />
        Form edits known fields only — comments and other keys are preserved.
      </p>

      <Field label="Name">
        <TextInput value={name} onChange={(v) => update((d) => d.setIn(['name'], v))} />
      </Field>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[11px] uppercase tracking-wide text-faint">Replenish</h3>
          <Checkbox checked={hasReplenish} onChange={setReplenishEnabled} label="Enabled" />
        </div>
        {hasReplenish ? (
          <div className="grid grid-cols-3 gap-3">
            <Field label="Kind">
              <Select
                value={replenishKind}
                onChange={(v) => update((d) => d.setIn(['replenish', 'kind'], v))}
                options={REPLENISH_KINDS.map((k) => ({ value: k, label: k }))}
              />
            </Field>
            <Field label="Ref">
              <TextInput
                value={replenishRef}
                onChange={(v) =>
                  update((d) => (v ? d.setIn(['replenish', 'ref'], v) : safeDeleteIn(d, ['replenish', 'ref'])))
                }
              />
            </Field>
            <Field label="Task">
              <TextInput
                value={replenishTask}
                onChange={(v) => update((d) => d.setIn(['replenish', 'task'], v))}
              />
            </Field>
          </div>
        ) : (
          <p className="text-[12px] text-faint">Drain-only loop (Mode B) — no replenish step.</p>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-[11px] uppercase tracking-wide text-faint">Stop</h3>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Max cycles">
            <NumberInput
              value={maxCycles}
              onChange={(v) => update((d) => d.setIn(['stop', 'max_cycles'], v === '' ? 1 : v))}
            />
          </Field>
          <div className="flex items-end pb-1.5">
            <Checkbox
              checked={onNoNewWork}
              onChange={(v) => update((d) => d.setIn(['stop', 'on_no_new_work'], v))}
              label="Stop on no new work"
            />
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between">
          <h4 className="text-[11px] uppercase tracking-wide text-faint">Budget</h4>
          <Checkbox checked={hasBudget} onChange={setBudgetEnabled} label="Enabled" />
        </div>
        {hasBudget && (
          <div className="mt-2 grid grid-cols-2 gap-3">
            <Field label="Unit">
              <Select
                value={budgetUnit}
                onChange={(v) => update((d) => d.setIn(['stop', 'budget', 'unit'], v))}
                options={BUDGET_UNITS.map((u) => ({ value: u, label: u }))}
              />
            </Field>
            <Field label="Max">
              <NumberInput
                value={budgetMax}
                onChange={(v) => update((d) => d.setIn(['stop', 'budget', 'max'], v === '' ? 1 : v))}
              />
            </Field>
          </div>
        )}
      </section>
    </div>
  )
}
