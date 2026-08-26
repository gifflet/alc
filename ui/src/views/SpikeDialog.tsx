// SpikeDialog.tsx — Launch a spike: a ceremony-free run against a bare task.
//
// Unlike run/flow/specialist, a spike has no blueprint, manifest unit or
// worktree isolation to pick — just a task and (optionally) an engine.
import { useState } from 'react'
import { ApiError } from '../api/client'
import { useEngines } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { Dialog, DialogButton } from '../components/Dialog'
import { Field, Select, TextArea } from '../components/fields'

export function SpikeDialog({ onClose }: { onClose: () => void }) {
  const id = useProjectId()
  const start = useStartExec()
  const engines = useEngines(id).data ?? []

  const [task, setTask] = useState('')
  const [engine, setEngine] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    const args: Record<string, unknown> = { task }
    if (engine) args.engine = engine
    setSaving(true)
    setError(null)
    try {
      await start('spike', args)
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

  return (
    <Dialog
      title="Spike"
      onClose={onClose}
      width={520}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onClose}>
            Cancel
          </DialogButton>
          <DialogButton onClick={submit} disabled={!task.trim() || saving}>
            Run
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-[length:var(--ui-text-body)] text-muted">
          A spike is a ceremony-free run: no blueprint, no manifest unit — just a task.
        </p>

        <Field label="Task">
          <TextArea value={task} onChange={setTask} rows={5} placeholder="Describe the spike…" />
        </Field>

        <Field label="Engine">
          <Select value={engine} onChange={setEngine} options={engineOptions} />
        </Field>

        {error && <p className="text-[length:var(--ui-text-label)] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
