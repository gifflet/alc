// SpecialistForm.tsx — Structured editor over a Specialist's YAML
// (.alc/specialists/<name>.yaml).
//
// Edits are applied to a parsed YAML Document and re-serialised, so comments and
// any keys the form does not surface survive untouched — same contract as
// FlowForm/LoopForm. `blueprint` names the Blueprint run for the Act step
// (models.Specialist); it is a Select when the project's blueprint names are
// readily available (SourceEditor already fetches the `blueprints` collection
// for this), and falls back to a plain text input otherwise.
import { parseDocument } from 'yaml'
import type { Document } from 'yaml'
import { Info } from 'lucide-react'
import { Field, Select, TextInput } from '../../components/fields'

export function SpecialistForm({
  value,
  onChange,
  blueprintNames,
}: {
  value: string
  onChange: (raw: string) => void
  blueprintNames: string[]
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

  const name = String(doc.get('name') ?? '')
  const area = String(doc.get('area') ?? '')
  const blueprint = String(doc.get('blueprint') ?? '')
  const knowledgePath = String(doc.get('knowledge_path') ?? '')

  // The current value always stays selectable even if it fell out of the
  // project's blueprint list (renamed/deleted elsewhere) — same dedup as
  // BlueprintForm's compute-tier options.
  const blueprintOptions = Array.from(new Set([blueprint, ...blueprintNames].filter(Boolean)))

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
        <Field label="Area">
          <TextInput
            value={area}
            onChange={(v) => update((d) => d.setIn(['area'], v))}
            placeholder="What this Specialist keeps a working model of"
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Blueprint">
          {blueprintNames.length > 0 ? (
            <Select
              value={blueprint}
              onChange={(v) => update((d) => d.setIn(['blueprint'], v))}
              options={blueprintOptions.map((b) => ({ value: b, label: b }))}
            />
          ) : (
            <TextInput value={blueprint} onChange={(v) => update((d) => d.setIn(['blueprint'], v))} mono />
          )}
        </Field>
        <Field label="Knowledge path">
          <TextInput
            value={knowledgePath}
            onChange={(v) => update((d) => d.setIn(['knowledge_path'], v))}
            placeholder=".alc/knowledge/<name>.md"
            mono
          />
        </Field>
      </div>
    </div>
  )
}
