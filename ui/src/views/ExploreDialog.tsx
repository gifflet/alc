// ExploreDialog.tsx — Launch `alc explore`: N variants of the same Blueprint+task,
// each dispatched into its own isolated worktree — never auto-merged, so
// Compare can later show them side by side and Adopt picks the winner.
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { useCollection, useEngines } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { Dialog, DialogButton } from '../components/Dialog'
import { Field, NumberInput, Select, TextArea } from '../components/fields'

export function ExploreDialog({ onClose }: { onClose: () => void }) {
  const id = useProjectId()
  const start = useStartExec()
  const blueprints = useCollection(id, 'blueprints').data ?? []
  const engines = useEngines(id).data ?? []
  const tiers = Array.from(new Set(engines.flatMap((e) => Object.keys(e.tiers))))

  const [blueprint, setBlueprint] = useState('')
  const [task, setTask] = useState('')
  const [variants, setVariants] = useState<number | ''>(2)
  const [engine, setEngine] = useState('')
  const [tier, setTier] = useState('')
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
    if (engine) args.engine = engine
    if (tier) args.tier = tier
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

  const engineOptions = [
    { value: '', label: 'default' },
    ...engines.map((e) => ({ value: e.name, label: e.default ? `${e.name} (default)` : e.name })),
  ]
  const tierOptions = [{ value: '', label: 'default' }, ...tiers.map((t) => ({ value: t, label: t }))]

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
        <p className="text-[12px] text-muted">
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

        <div className="grid grid-cols-3 gap-3">
          <Field label="Variants">
            <NumberInput value={variants} onChange={setVariants} placeholder="2" />
          </Field>
          <Field label="Engine">
            <Select value={engine} onChange={setEngine} options={engineOptions} />
          </Field>
          <Field label="Tier">
            <Select value={tier} onChange={setTier} options={tierOptions} />
          </Field>
        </div>

        {error && <p className="text-[11px] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
