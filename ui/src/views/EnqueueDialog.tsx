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

/** Split a batch textarea into one task per non-blank line. */
function batchLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

export function EnqueueDialog({
  onClose,
  onSubmit,
  onSubmitBatch,
  pending,
  saving,
  error,
}: {
  onClose: () => void
  onSubmit: (task: Partial<QueueTask>) => void
  onSubmitBatch: (tasks: Partial<QueueTask>[]) => void
  pending: PendingTask[]
  saving: boolean
  error: string | null
}) {
  const id = useProjectId()
  const flows = useCollection(id, 'flows').data ?? []
  const specialists = useCollection(id, 'specialists').data ?? []
  const blueprints = useCollection(id, 'blueprints').data ?? []

  const [mode, setMode] = useState<'single' | 'batch'>('single')
  const [kind, setKind] = useState<'flow' | 'specialist' | 'run'>('flow')
  const [name, setName] = useState('')
  const [task, setTask] = useState('')
  const [batchText, setBatchText] = useState('')
  const [isolate, setIsolate] = useState(true)
  const [taskId, setTaskId] = useState('')
  const [deps, setDeps] = useState<string[]>([])

  // `run` queues a bare Blueprint — the chore-sized task that used to need a
  // wrapper flow written by hand (dogfood finding 8).
  const units = kind === 'flow' ? flows : kind === 'run' ? blueprints : specialists
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

  const tasks = batchLines(batchText)

  const submit = () => {
    if (mode === 'batch') {
      onSubmitBatch(tasks.map((line) => ({ kind, name, task: line, isolate })))
      return
    }
    const payload: Partial<QueueTask> = { kind, name, task, isolate }
    if (taskId.trim()) payload.id = taskId.trim()
    if (deps.length) payload.depends_on = deps
    onSubmit(payload)
  }

  const canSubmit = mode === 'batch' ? Boolean(name && tasks.length > 0) : Boolean(name && task.trim())

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
            {mode === 'batch' && tasks.length > 0 ? `Enqueue ${tasks.length}` : 'Enqueue'}
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-3 gap-3">
          <Field label="Kind">
            <Select
              value={kind}
              onChange={(v) => setKind(v as 'flow' | 'specialist' | 'run')}
              options={[
                { value: 'flow', label: 'flow' },
                { value: 'specialist', label: 'specialist' },
                { value: 'run', label: 'blueprint' },
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
          <Field label="Mode">
            <Select
              value={mode}
              onChange={(v) => setMode(v as 'single' | 'batch')}
              options={[
                { value: 'single', label: 'One task' },
                { value: 'batch', label: 'Batch' },
              ]}
            />
          </Field>
        </div>

        {mode === 'single' ? (
          <Field label="Task">
            <TextArea value={task} onChange={setTask} rows={5} placeholder="Describe the task…" />
          </Field>
        ) : (
          <Field
            label="Tasks (one per line)"
            hint={`${tasks.length} task(s) will be enqueued, sharing kind/unit/isolate above.`}
          >
            <TextArea
              value={batchText}
              onChange={setBatchText}
              rows={6}
              placeholder={'Describe each task on its own line…'}
            />
          </Field>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Checkbox checked={isolate} onChange={setIsolate} label="Run in an isolated worktree" />
          {mode === 'single' && (
            <Field label="Id (optional)">
              <TextInput value={taskId} onChange={setTaskId} placeholder="slug" mono />
            </Field>
          )}
        </div>

        {mode === 'single' && depOptions.length > 0 && (
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

        {error && <p className="text-[length:var(--ui-text-label)] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}
