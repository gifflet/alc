// StringListEditor.tsx — Add/remove editor for a flat `list[str]` YAML node
// (protected-path globs, quarantined check names, …). Shared by BlueprintForm
// (`protect`) and ManifestForm (`quarantined_checks`).
import { Plus, Trash2 } from 'lucide-react'

export function StringListEditor({
  values,
  onChange,
  placeholder,
  emptyLabel = 'None.',
}: {
  values: string[]
  onChange: (next: string[]) => void
  placeholder?: string
  emptyLabel?: string
}) {
  const setAt = (i: number, v: string) => onChange(values.map((x, idx) => (idx === i ? v : x)))
  const removeAt = (i: number) => onChange(values.filter((_, idx) => idx !== i))
  const add = () => onChange([...values, ''])

  return (
    <div className="flex flex-col gap-1.5">
      {values.length === 0 && <p className="text-[12px] text-faint">{emptyLabel}</p>}
      {values.map((v, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            value={v}
            onChange={(e) => setAt(i, e.target.value)}
            placeholder={placeholder}
            spellCheck={false}
            className="flex-1 rounded-panel border border-border bg-base px-2 py-1 font-mono text-[12px] text-primary outline-none focus:border-accent"
          />
          <button
            type="button"
            aria-label={`Remove ${v || `item ${i + 1}`}`}
            onClick={() => removeAt(i)}
            className="flex h-6 w-6 items-center justify-center text-faint hover:text-error"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="flex w-fit items-center gap-1 rounded-panel border border-border px-2 py-1 text-[11px] text-muted hover:bg-hover hover:text-primary"
      >
        <Plus className="h-3 w-3" />
        Add
      </button>
    </div>
  )
}
