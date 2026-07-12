// EnqueueDialog.tsx — Compose a QueueTask and enqueue it (kind/unit/task/deps).
import { useEffect, useState } from 'react'
import { useCollection } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { Dialog, DialogButton } from '../components/Dialog'
import { Checkbox, Field, Select, TextArea, TextInput } from '../components/fields'
import type { PendingTask, QueueTask } from '../api/types'

function firstLine(text: string): string {
  return text.split('\n')[0]
}

export function EnqueueDialog({
  onClose,
  onSubmit,
  pending,
  saving,
  error,
}: {
  onClose: () => void
  onSubmit: (task: Partial<QueueTask>) => void
  pending: PendingTask[]
  saving: boolean
  error: string | null
}) {
  const id = useProjectId()
  const flows = useCollection(id, 'flows').data ?? []
  const specialists = useCollection(id, 'specialists').data ?? []

  const [kind, setKind] = useState<'flow' | 'specialist'>('flow')
  const [name, setName] = useState('')
  const [task, setTask] = useState('')
  const [isolate, setIsolate] = useState(true)
  const [taskId, setTaskId] = useState('')
  const [deps, setDeps] = useState<string[]>([])

  const units = kind === 'flow' ? flows : specialists
  // Keep the unit selection valid as the kind toggles or the lists load.
  useEffect(() => {
    if (units.length && !units.some((u) => u.name === name)) setName(units[0].name)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, units.length])

  const depOptions = pending
    .filter((p) => p.task.id)
    .map((p) => ({ id: p.task.id as string, label: firstLine(p.task.task) }))

  const toggleDep = (depId: string) =>
    setDeps((cur) => (cur.includes(depId) ? cur.filter((d) => d !== depId) : [...cur, depId]))

  const submit = () => {
    const payload: Partial<QueueTask> = { kind, name, task, isolate }
    if (taskId.trim()) payload.id = taskId.trim()
    if (deps.length) payload.depends_on = deps
    onSubmit(payload)
  }

  const canSubmit = Boolean(name && task.trim())

  return (
    <Dialog
      title="Enqueue task"
      onClose={onClose}
      width={520}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onClose}>
            Cancel
          </DialogButton>
          <DialogButton onClick={submit} disabled={!canSubmit || saving}>
            Enqueue
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Kind">
            <Select
              value={kind}
              onChange={(v) => setKind(v as 'flow' | 'specialist')}
              options={[
                { value: 'flow', label: 'flow' },
                { value: 'specialist', label: 'specialist' },
              ]}
            />
          </Field>
          <Field label="Unit">
            <Select
              value={name}
              onChange={setName}
              options={units.map((u) => ({ value: u.name, label: u.name }))}
            />
          </Field>
        </div>

        <Field label="Task">
          <TextArea value={task} onChange={setTask} rows={5} placeholder="Describe the task…" />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Checkbox checked={isolate} onChange={setIsolate} label="Run in an isolated worktree" />
          <Field label="Id (optional)">
            <TextInput value={taskId} onChange={setTaskId} placeholder="slug" mono />
          </Field>
        </div>

        {depOptions.length > 0 && (
          <Field label="Depends on">
            <div className="flex flex-col gap-1 rounded-panel border border-border bg-base p-2">
              {depOptions.map((d) => (
                <Checkbox
                  key={d.id}
                  checked={deps.includes(d.id)}
                  onChange={() => toggleDep(d.id)}
                  label={`${d.id} — ${d.label}`}
                />
              ))}
            </div>
          </Field>
        )}

        {error && <p className="text-[11px] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
