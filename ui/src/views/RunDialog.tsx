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
import { MoreOptions } from '../components/MoreOptions'

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
  // Mirrors `alc run`, where --isolate is opt-in. Enqueue defaults it ON
  // because unattended work must not touch the operator's tree — same words,
  // opposite defaults, and both are defensible. Changing this would make the UI
  // disagree with the CLI, so it stays until that is decided deliberately.
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

        {/* Each of these has a correct default in the manifest. Asking all
            three at the weight of the task turns one question into four,
            three of which need vocabulary the person may not have. */}
        <MoreOptions hint="engine, compute tier, isolation">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Engine" hint="Which coding agent does the work">
              <Select value={engine} onChange={setEngine} options={engineOptions} />
            </Field>
            {advanced && (
              <Field label="Tier" hint="How much model to spend on it">
                <Select
                  value={tier}
                  onChange={setTier}
                  options={[{ value: '', label: 'default' }, ...tiers.map((t) => ({ value: t, label: t }))]}
                />
              </Field>
            )}
          </div>

          {advanced && (
            // Named as what it does to your files, which is the part that
            // matters before you press the button.
            <Checkbox
              checked={isolate}
              onChange={setIsolate}
              label="Work on a separate branch, leaving my files untouched"
            />
          )}
        </MoreOptions>

        {error && <p className="text-[length:var(--ui-text-label)] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
