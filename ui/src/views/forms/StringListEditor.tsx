// StringListEditor.tsx — Add/remove editor for a flat `list[str]` YAML node
// (protected-path globs, quarantined check names, …). Shared by BlueprintForm
// (`protect`) and ManifestForm (`quarantined_checks`).
import { Plus, Trash2 } from 'lucide-react'
import { ActionButton } from '../../components/ActionButton'

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
      {values.length === 0 && <p className="text-[length:var(--ui-text-body)] text-faint">{emptyLabel}</p>}
      {values.map((v, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            value={v}
            onChange={(e) => setAt(i, e.target.value)}
            placeholder={placeholder}
            spellCheck={false}
            className="flex-1 rounded-panel border border-border bg-base px-2 py-1 font-mono text-[length:var(--ui-text-body)] text-primary outline-none focus:border-accent"
          />
          <button
            type="button"
            aria-label={`Remove ${v || `item ${i + 1}`}`}
            onClick={() => removeAt(i)}
            className="flex min-h-[var(--ui-control-h)] min-w-[var(--ui-control-h)] items-center justify-center text-faint hover:text-error"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <ActionButton
        onClick={add}
        tone="ghost"
        size="sm"
      >
        <Plus className="h-3 w-3" />
        Add
      </ActionButton>
    </div>
  )
}
