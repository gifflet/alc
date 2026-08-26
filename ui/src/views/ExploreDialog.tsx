// ExploreDialog.tsx — Launch `alc explore`: N variants of the same Blueprint+task,
// each dispatched into its own isolated worktree — never auto-merged, so
// Compare can later show them side by side and Adopt picks the winner.
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { useCollection, useEngines } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { Dialog, DialogButton } from '../components/Dialog'
import { Checkbox, Field, NumberInput, Select, TextArea } from '../components/fields'

// Toggle membership of `value` in a string list — the same pattern
// EnqueueDialog uses for its "Depends on" checkbox group.
function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

export function ExploreDialog({ onClose }: { onClose: () => void }) {
  const id = useProjectId()
  const start = useStartExec()
  const blueprints = useCollection(id, 'blueprints').data ?? []
  const engines = useEngines(id).data ?? []
  const tiers = Array.from(new Set(engines.flatMap((e) => Object.keys(e.tiers))))

  const [blueprint, setBlueprint] = useState('')
  const [task, setTask] = useState('')
  const [variants, setVariants] = useState<number | ''>(2)
  // Cartesian product: `alc explore` crosses every picked engine with every
  // picked tier (and with --variants). Empty means "use the CLI's default".
  const [selectedEngines, setSelectedEngines] = useState<string[]>([])
  const [selectedTiers, setSelectedTiers] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Keep the blueprint selection valid once the collection loads.
  useEffect(() => {
    if (blueprints.length && !blueprints.some((b) => b.name === blueprint)) {
      setBlueprint(blueprints[0].name)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blueprints.length])

  const submit = async () => {
    const args: Record<string, unknown> = {
      blueprint,
      task,
      variants: variants === '' ? 1 : variants,
    }
    if (selectedEngines.length) args.engine = selectedEngines
    if (selectedTiers.length) args.tier = selectedTiers
    setSaving(true)
    setError(null)
    try {
      await start('explore', args)
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to start.')
      setSaving(false)
    }
  }

  const canSubmit = Boolean(blueprint && task.trim() && (variants === '' || variants >= 1))

  return (
    <Dialog
      title="Explore variants"
      onClose={onClose}
      width={520}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onClose}>
            Cancel
          </DialogButton>
          <DialogButton onClick={submit} disabled={!canSubmit || saving}>
            Explore
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-[length:var(--ui-text-body)] text-muted">
          Runs N copies of the same Blueprint+task in isolated worktrees, side by side. Never
          auto-merges — Compare then Adopt closes the loop.
        </p>

        <Field label="Blueprint">
          <Select
            value={blueprint}
            onChange={setBlueprint}
            options={blueprints.map((b) => ({ value: b.name, label: b.name }))}
          />
        </Field>

        <Field label="Task">
          <TextArea value={task} onChange={setTask} rows={4} placeholder="Describe the task…" />
        </Field>

        <Field label="Variants">
          <NumberInput value={variants} onChange={setVariants} placeholder="2" />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <span className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Engines</span>
            <div className="flex flex-col gap-1 rounded-panel border border-border bg-base p-2">
              {engines.length === 0 && <p className="text-[length:var(--ui-text-label)] text-faint">No engines configured.</p>}
              {engines.map((e) => (
                <Checkbox
                  key={e.name}
                  checked={selectedEngines.includes(e.name)}
                  onChange={() => setSelectedEngines((cur) => toggle(cur, e.name))}
                  label={e.default ? `${e.name} (default)` : e.name}
                />
              ))}
            </div>
            <span className="text-[length:var(--ui-text-label)] text-faint">none selected = manifest default</span>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">Tiers</span>
            <div className="flex flex-col gap-1 rounded-panel border border-border bg-base p-2">
              {tiers.length === 0 && <p className="text-[length:var(--ui-text-label)] text-faint">No tiers configured.</p>}
              {tiers.map((t) => (
                <Checkbox
                  key={t}
                  checked={selectedTiers.includes(t)}
                  onChange={() => setSelectedTiers((cur) => toggle(cur, t))}
                  label={t}
                />
              ))}
            </div>
            <span className="text-[length:var(--ui-text-label)] text-faint">none selected = blueprint default</span>
          </div>
        </div>

        {error && <p className="text-[length:var(--ui-text-label)] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
