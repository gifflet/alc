// RunDialog.tsx — Launch a blueprint (run), flow, or specialist against a task.
//
// The IDE "Run" affordance: pick the task text, engine, compute tier and (for
// run/flow) an isolated worktree, then dispatch an exec and open the console.
// Field set narrows by command — specialists take neither tier nor isolate.
import { useState } from 'react'
import { ApiError } from '../api/client'
import { useEngines } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { Dialog, DialogButton } from '../components/Dialog'
import { Checkbox, Field, Select, TextArea } from '../components/fields'

export type RunCommand = 'run' | 'flow' | 'specialist'

const TITLE: Record<RunCommand, string> = {
  run: 'Run blueprint',
  flow: 'Run flow',
  specialist: 'Run specialist',
}

/** The positional key each command expects the unit name under. */
const NAME_KEY: Record<RunCommand, string> = {
  run: 'blueprint',
  flow: 'flow',
  specialist: 'name',
}

export function RunDialog({
  command,
  name,
  onClose,
}: {
  command: RunCommand
  name: string
  onClose: () => void
}) {
  const id = useProjectId()
  const start = useStartExec()
  const engines = useEngines(id).data ?? []
  const tiers = Array.from(new Set(engines.flatMap((e) => Object.keys(e.tiers))))

  const [task, setTask] = useState('')
  const [engine, setEngine] = useState('')
  const [tier, setTier] = useState('')
  const [isolate, setIsolate] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const advanced = command !== 'specialist'

  const submit = async () => {
    const args: Record<string, unknown> = { [NAME_KEY[command]]: name, task }
    if (engine) args.engine = engine
    if (advanced && tier) args.tier = tier
    if (advanced && isolate) args.isolate = true
    setSaving(true)
    setError(null)
    try {
      await start(command, args)
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
      title={`${TITLE[command]} · ${name}`}
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
        <Field label="Task">
          <TextArea value={task} onChange={setTask} rows={5} placeholder="Describe the task…" />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Engine">
            <Select value={engine} onChange={setEngine} options={engineOptions} />
          </Field>
          {advanced && (
            <Field label="Tier">
              <Select
                value={tier}
                onChange={setTier}
                options={[{ value: '', label: 'default' }, ...tiers.map((t) => ({ value: t, label: t }))]}
              />
            </Field>
          )}
        </div>

        {advanced && (
          <Checkbox checked={isolate} onChange={setIsolate} label="Run in an isolated git worktree" />
        )}

        {error && <p className="text-[11px] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
