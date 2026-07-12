// ManifestForm.tsx — Structured editor over manifest.yaml (IntelliJ-settings feel).
//
// Edits are applied to a parsed YAML Document and re-serialised, so comments and
// any keys the form does not surface survive untouched. The same `value` string
// backs both this form and the Source editor; the server is the only validator.
import { parseDocument } from 'yaml'
import type { Document } from 'yaml'
import { Info } from 'lucide-react'
import { Field, NumberInput, Select } from '../../components/fields'

const KNOBS: { key: string; label: string; def: number }[] = [
  { key: 'default_timeout_s', label: 'Default timeout (s)', def: 1800 },
  { key: 'plan_retries', label: 'Plan retries', def: 2 },
  { key: 'fanout_concurrency', label: 'Fanout concurrency', def: 4 },
  { key: 'max_task_retries', label: 'Max task retries', def: 0 },
]

function mapKeys(node: unknown): string[] {
  const items = (node as { items?: { key: { value?: unknown } }[] } | null)?.items
  return items ? items.map((p) => String(p.key.value ?? p.key)) : []
}

export function ManifestForm({
  value,
  onChange,
}: {
  value: string
  onChange: (raw: string) => void
}) {
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

  const engines = mapKeys(doc.get('engines'))
  const tiers = mapKeys(doc.get('compute_tiers'))
  // Column set: every engine declared, plus any engine referenced by a tier.
  const columns = Array.from(
    new Set([...engines, ...tiers.flatMap((t) => mapKeys(doc.getIn(['compute_tiers', t])))]),
  )
  const defaultEngine = String(doc.get('default_engine') ?? '')
  const strategy = String(doc.get('retry_strategy') ?? 'immediate')

  const cell = (tier: string, engine: string): string => {
    const v = doc.getIn(['compute_tiers', tier, engine])
    return v == null ? '' : String(v)
  }

  return (
    <div className="flex flex-col gap-4 overflow-auto p-4">
      <p className="flex items-center gap-1.5 text-[11px] text-faint">
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

      <section>
        <h3 className="mb-2 text-[11px] uppercase tracking-wide text-faint">Compute tiers</h3>
        {tiers.length === 0 || columns.length === 0 ? (
          <p className="text-[12px] text-faint">No tiers declared.</p>
        ) : (
          <table className="w-full border-collapse text-[12px]">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-faint">
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
                <tr key={tier} className="border-b border-border/60">
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
                        className="w-full rounded-panel border border-border bg-base px-2 py-1 font-mono text-[12px] text-primary outline-none focus:border-accent"
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-[11px] uppercase tracking-wide text-faint">Knobs</h3>
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
    </div>
  )
}
