// FlowForm.tsx — Structured editor over a Flow's YAML (.alc/flows/<name>.yaml).
//
// Edits are applied to a parsed YAML Document and re-serialised, so comments and
// any keys the form does not surface survive untouched — same contract as
// ManifestForm. A stage runs exactly one of blueprint/specialist (models.FlowStage);
// `derive_checks` is only meaningful on a verify_only stage.
import { parseDocument } from 'yaml'
import type { Document } from 'yaml'
import { Info, Plus, Trash2 } from 'lucide-react'
import { Checkbox, Field, TextInput } from '../../components/fields'
import { safeDeleteIn } from '../../lib/yamlDoc'

type RefKind = 'blueprint' | 'specialist'

interface DeriveChecks {
  fromStage: string
  field: string
  shellTemplate: string
}

interface StageRow {
  name: string
  refKind: RefKind
  ref: string
  verifyOnly: boolean
  deriveChecks: DeriveChecks | null
}

function readStages(doc: Document): StageRow[] {
  const seq = doc.getIn(['stages']) as { items?: unknown[] } | null
  if (!seq?.items) return []
  return seq.items.map((_, i) => {
    const at = (...rest: (string | number)[]) => doc.getIn(['stages', i, ...rest])
    const name = String(at('name') ?? '')
    const specialist = at('specialist')
    const refKind: RefKind = specialist != null ? 'specialist' : 'blueprint'
    const ref = String((refKind === 'specialist' ? specialist : at('blueprint')) ?? '')
    const verifyOnly = Boolean(at('verify_only'))
    const deriveChecks = doc.hasIn(['stages', i, 'derive_checks'])
      ? {
          fromStage: String(at('derive_checks', 'from_stage') ?? ''),
          field: String(at('derive_checks', 'field') ?? ''),
          shellTemplate: String(at('derive_checks', 'shell_template') ?? ''),
        }
      : null
    return { name, refKind, ref, verifyOnly, deriveChecks }
  })
}

export function FlowForm({ value, onChange }: { value: string; onChange: (raw: string) => void }) {
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
  const description = String(doc.get('description') ?? '')
  const stages = readStages(doc)

  const setStage = (i: number, row: StageRow) =>
    update((d) => {
      d.setIn(['stages', i, 'name'], row.name)
      if (row.refKind === 'blueprint') {
        d.setIn(['stages', i, 'blueprint'], row.ref)
        safeDeleteIn(d, ['stages', i, 'specialist'])
      } else {
        d.setIn(['stages', i, 'specialist'], row.ref)
        safeDeleteIn(d, ['stages', i, 'blueprint'])
      }
      if (row.verifyOnly) d.setIn(['stages', i, 'verify_only'], true)
      else safeDeleteIn(d, ['stages', i, 'verify_only'])
      if (row.verifyOnly && row.deriveChecks) {
        d.setIn(['stages', i, 'derive_checks', 'from_stage'], row.deriveChecks.fromStage)
        d.setIn(['stages', i, 'derive_checks', 'field'], row.deriveChecks.field)
        d.setIn(['stages', i, 'derive_checks', 'shell_template'], row.deriveChecks.shellTemplate)
      } else {
        safeDeleteIn(d, ['stages', i, 'derive_checks'])
      }
    })

  const addStage = () =>
    update((d) => {
      const seq = d.getIn(['stages']) as { add?: (v: unknown) => void } | null
      const item = { name: 'stage', blueprint: '' }
      if (seq?.add) seq.add(item)
      else d.setIn(['stages'], [item])
    })

  const removeStage = (i: number) => update((d) => d.deleteIn(['stages', i]))

  const toggleVerifyOnly = (row: StageRow, i: number, v: boolean) =>
    setStage(i, {
      ...row,
      verifyOnly: v,
      // verify_only must reference a blueprint (models.FlowStage._exactly_one_ref).
      refKind: v ? 'blueprint' : row.refKind,
      deriveChecks: v ? row.deriveChecks : null,
    })

  const toggleDeriveChecks = (row: StageRow, i: number, on: boolean) =>
    setStage(i, { ...row, deriveChecks: on ? { fromStage: '', field: '', shellTemplate: '{value}' } : null })

  return (
    <div className="flex flex-col gap-4 overflow-auto p-4">
      <p className="flex items-center gap-1.5 text-[11px] text-faint">
        <Info className="h-3.5 w-3.5" />
        Form edits known fields only — comments and other keys are preserved.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Name">
          <TextInput value={name} onChange={(v) => update((d) => d.setIn(['name'], v))} />
        </Field>
        <Field label="Description">
          <TextInput value={description} onChange={(v) => update((d) => d.setIn(['description'], v))} />
        </Field>
      </div>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[11px] uppercase tracking-wide text-faint">Stages</h3>
          <button
            type="button"
            onClick={addStage}
            className="flex items-center gap-1 rounded-panel border border-border px-2 py-1 text-[11px] text-muted hover:bg-hover hover:text-primary"
          >
            <Plus className="h-3 w-3" />
            Add stage
          </button>
        </div>
        {stages.length === 0 ? (
          <p className="text-[12px] text-faint">No stages.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {stages.map((row, i) => (
              <div key={i} className="flex flex-col gap-2 rounded-panel border border-border p-2">
                <div className="flex items-center gap-2">
                  <input
                    value={row.name}
                    onChange={(e) => setStage(i, { ...row, name: e.target.value })}
                    placeholder="stage name"
                    aria-label="Stage name"
                    spellCheck={false}
                    className="w-28 rounded-panel border border-border bg-base px-2 py-1 text-[12px] text-primary outline-none focus:border-accent"
                  />
                  <select
                    value={row.refKind}
                    onChange={(e) => setStage(i, { ...row, refKind: e.target.value as RefKind })}
                    disabled={row.verifyOnly}
                    aria-label="Stage ref kind"
                    className="rounded-panel border border-border bg-base px-2 py-1 text-[12px] text-primary outline-none focus:border-accent disabled:opacity-50"
                  >
                    <option value="blueprint">blueprint</option>
                    <option value="specialist">specialist</option>
                  </select>
                  <input
                    value={row.ref}
                    onChange={(e) => setStage(i, { ...row, ref: e.target.value })}
                    placeholder={row.refKind === 'blueprint' ? 'blueprint name' : 'specialist name'}
                    aria-label="Stage ref name"
                    spellCheck={false}
                    className="flex-1 rounded-panel border border-border bg-base px-2 py-1 font-mono text-[12px] text-primary outline-none focus:border-accent"
                  />
                  <button
                    type="button"
                    aria-label={`Remove ${row.name || `stage ${i + 1}`}`}
                    onClick={() => removeStage(i)}
                    className="flex h-6 w-6 items-center justify-center text-faint hover:text-error"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                <Checkbox
                  checked={row.verifyOnly}
                  onChange={(v) => toggleVerifyOnly(row, i, v)}
                  label="Verify only (run checks as a pure gate, no engine turn)"
                />

                {row.verifyOnly && (
                  <div className="flex flex-col gap-2 border-t border-border/60 pt-2">
                    <Checkbox
                      checked={row.deriveChecks !== null}
                      onChange={(v) => toggleDeriveChecks(row, i, v)}
                      label="Derive checks from an earlier stage's report"
                    />
                    {row.deriveChecks && (
                      <div className="grid grid-cols-3 gap-2 pl-1">
                        <Field label="From stage">
                          <TextInput
                            value={row.deriveChecks.fromStage}
                            onChange={(v) =>
                              setStage(i, { ...row, deriveChecks: { ...row.deriveChecks!, fromStage: v } })
                            }
                          />
                        </Field>
                        <Field label="Field">
                          <TextInput
                            value={row.deriveChecks.field}
                            onChange={(v) =>
                              setStage(i, { ...row, deriveChecks: { ...row.deriveChecks!, field: v } })
                            }
                            placeholder="removed_symbols"
                          />
                        </Field>
                        <Field label="Shell template">
                          <TextInput
                            value={row.deriveChecks.shellTemplate}
                            onChange={(v) =>
                              setStage(i, { ...row, deriveChecks: { ...row.deriveChecks!, shellTemplate: v } })
                            }
                            placeholder="! grep -rn {value} src/"
                            mono
                          />
                        </Field>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
