// Queue.tsx — Pending tasks + archived (done) tasks with enqueue/retry/delete.
import { Fragment, useState } from 'react'
import { ChevronDown, ChevronRight, ListTodo, Play, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { useDeletePending, useEnqueueTask, useQueue, useRetryQueue } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useStartExec } from '../app/useStartExec'
import { ConfirmDialog, Dialog, DialogButton } from '../components/Dialog'
import { EmptyState } from '../components/EmptyState'
import { Field, NumberInput } from '../components/fields'
import { Loading, Pill } from '../components/primitives'
import { RelativeTime } from '../components/RelativeTime'
import { EnqueueDialog } from './EnqueueDialog'
import { ApiError } from '../api/client'
import type { DoneTask, FlowReport, PendingTask, QueueTask } from '../api/types'

function firstLine(text: string): string {
  return text.split('\n')[0]
}

/** A re-executed task's attempt number — surfaced so a retry is visible at a glance. */
function RetryBadge({ task }: { task: QueueTask | null }) {
  if (!task?.retries) return null
  return <Pill tone="warn">retry #{task.retries}</Pill>
}

/** The full task body — for a retry this shows the lineage root it descends from
 * plus the carried failure feedback appended below the intent, both of which the
 * one-line summary hides. */
function TaskBody({ task }: { task: QueueTask }) {
  return (
    <div className="border-l-2 border-border bg-base px-3 py-2">
      {task.retry_of && (
        <div className="mb-1 font-mono text-[11px] text-faint">
          ↩ retry lineage of <span className="text-muted">{task.retry_of}</span>
        </div>
      )}
      <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-muted">
        {task.task}
      </pre>
    </div>
  )
}

function DrainDialog({ onClose }: { onClose: () => void }) {
  const start = useStartExec()
  const [concurrency, setConcurrency] = useState<number | ''>(1)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      await start('tick', concurrency === '' ? {} : { concurrency })
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to start.')
      setSaving(false)
    }
  }

  return (
    <Dialog
      title="Drain queue"
      onClose={onClose}
      footer={
        <>
          <DialogButton tone="ghost" onClick={onClose}>
            Cancel
          </DialogButton>
          <DialogButton onClick={submit} disabled={saving}>
            Drain
          </DialogButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-[12px] text-muted">Process every pending task once (alc tick), then exit.</p>
        <Field label="Concurrency">
          <NumberInput value={concurrency} onChange={setConcurrency} placeholder="1" />
        </Field>
        {error && <p className="text-[11px] text-error">{error}</p>}
      </div>
    </Dialog>
  )
}

function ReportSummary({ report }: { report: FlowReport }) {
  return (
    <div className="border-l-2 border-border bg-base px-3 py-2 text-[11px]">
      <div className="flex flex-wrap gap-4 font-mono text-faint">
        <span>flow: {report.flow}</span>
        <span>engine: {report.engine}</span>
        <span>stages: {report.stages.length}</span>
        <span>
          scorecard: span={report.scorecard.span} passes={report.scorecard.passes} streak=
          {report.scorecard.streak} touch={report.scorecard.touch}
        </span>
        {report.commit_sha && <span>commit: {report.commit_sha.slice(0, 10)}</span>}
      </div>
    </div>
  )
}

function DoneRows({ done, onRetry }: { done: DoneTask[]; onRetry: (stem: string) => void }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <table className="w-full border-collapse text-[12px]">
      <thead>
        <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-faint">
          <th className="w-6 px-2 py-1" />
          <th className="px-2 py-1 font-medium">Task</th>
          <th className="w-20 px-2 py-1 font-medium">Result</th>
          <th className="w-24 px-2 py-1 font-medium">When</th>
          <th className="w-16 px-2 py-1 font-medium" />
        </tr>
      </thead>
      <tbody>
        {done.map((d) => {
          const open = expanded === d.stem
          const success = d.report?.success ?? null
          const failed = success === false
          return (
            <Fragment key={d.stem}>
              <tr
                role="button"
                tabIndex={0}
                aria-expanded={open}
                onClick={() => setExpanded(open ? null : d.stem)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setExpanded(open ? null : d.stem)
                  }
                }}
                className="h-[28px] cursor-pointer border-b border-border/60 transition-colors duration-120 hover:bg-hover"
              >
                <td className="px-2">
                  {d.report || d.task ? (
                    open ? (
                      <ChevronDown className="h-3.5 w-3.5 text-faint" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 text-faint" />
                    )
                  ) : null}
                </td>
                <td className="truncate px-2 text-muted">
                  <span className="flex items-center gap-2">
                    <span className="truncate">{d.task ? firstLine(d.task.task) : d.stem}</span>
                    <RetryBadge task={d.task} />
                  </span>
                </td>
                <td className="px-2">
                  {success === null ? (
                    <span className="text-faint">—</span>
                  ) : (
                    <Pill tone={success ? 'live' : 'error'}>{success ? 'ok' : 'failed'}</Pill>
                  )}
                </td>
                <td className="px-2">
                  <RelativeTime value={d.mtime} />
                </td>
                <td className="px-2">
                  {failed && (
                    <button
                      type="button"
                      aria-label={`Retry ${d.stem}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        onRetry(d.stem)
                      }}
                      className="flex items-center gap-1 rounded-panel border border-border px-1.5 py-0.5 text-[11px] text-muted hover:bg-hover hover:text-primary"
                    >
                      <RotateCcw className="h-3 w-3" />
                      retry
                    </button>
                  )}
                </td>
              </tr>
              {open && (
                <tr>
                  <td colSpan={5} className="p-0">
                    {d.task && <TaskBody task={d.task} />}
                    {d.report && <ReportSummary report={d.report} />}
                  </td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

function PendingRows({
  pending,
  onDelete,
}: {
  pending: PendingTask[]
  onDelete: (stem: string) => void
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <table className="w-full border-collapse text-[12px]">
      <thead>
        <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-faint">
          <th className="w-6 px-2 py-1" />
          <th className="px-2 py-1 font-medium">Task</th>
          <th className="w-20 px-2 py-1 font-medium">Kind</th>
          <th className="w-28 px-2 py-1 font-medium">Unit</th>
          <th className="w-16 px-2 py-1 font-medium">Isolate</th>
          <th className="w-28 px-2 py-1 font-medium">Depends on</th>
          <th className="w-10 px-2 py-1 font-medium" />
        </tr>
      </thead>
      <tbody>
        {pending.map((p) => {
          const open = expanded === p.stem
          return (
            <Fragment key={p.stem}>
              <tr
                role="button"
                tabIndex={0}
                aria-expanded={open}
                onClick={() => setExpanded(open ? null : p.stem)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setExpanded(open ? null : p.stem)
                  }
                }}
                className="group h-[28px] cursor-pointer border-b border-border/60 transition-colors duration-120 hover:bg-hover"
              >
                <td className="px-2">
                  {open ? (
                    <ChevronDown className="h-3.5 w-3.5 text-faint" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 text-faint" />
                  )}
                </td>
                <td className="truncate px-2 text-muted">
                  <span className="flex items-center gap-2">
                    <span className="truncate">{firstLine(p.task.task)}</span>
                    <RetryBadge task={p.task} />
                  </span>
                </td>
                <td className="px-2 font-mono text-faint">{p.task.kind}</td>
                <td className="px-2 text-muted">{p.task.name ?? p.task.flow}</td>
                <td className="px-2">
                  {p.task.isolate ? (
                    <Pill tone="accent">yes</Pill>
                  ) : (
                    <span className="text-faint">no</span>
                  )}
                </td>
                <td className="px-2 font-mono text-faint">
                  {p.task.depends_on.length ? p.task.depends_on.join(', ') : '—'}
                </td>
                <td className="px-2">
                  <button
                    type="button"
                    aria-label={`Delete ${p.stem}`}
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(p.stem)
                    }}
                    className="flex h-4 w-4 items-center justify-center text-faint opacity-0 transition-opacity duration-120 hover:text-error group-hover:opacity-100"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
              {open && (
                <tr>
                  <td colSpan={7} className="p-0">
                    <TaskBody task={p.task} />
                  </td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

export function Queue() {
  const id = useProjectId()
  const { data, isLoading } = useQueue(id)
  const enqueue = useEnqueueTask(id)
  const retry = useRetryQueue(id)
  const del = useDeletePending(id)
  const [enqueuing, setEnqueuing] = useState(false)
  const [draining, setDraining] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  if (isLoading) return <Loading />
  const pending = data?.pending ?? []
  const done = data?.done ?? []
  const failures = done.filter((d) => d.report && !d.report.success)

  const submitEnqueue = (task: Parameters<typeof enqueue.mutate>[0]) =>
    enqueue.mutate(task, {
      onSuccess: () => {
        setEnqueuing(false)
        enqueue.reset()
      },
    })

  const confirmDelete = () => {
    if (!deleting) return
    del.mutate(deleting, { onSuccess: () => setDeleting(null) })
  }

  const empty = pending.length === 0 && done.length === 0

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-panel px-4 py-2">
        <h2 className="text-[12px] font-medium text-primary">Queue</h2>
        <div className="flex items-center gap-2">
          {failures.length > 0 && (
            <button
              type="button"
              onClick={() => retry.mutate({ all: true })}
              className="flex items-center gap-1 rounded-panel border border-border px-2 py-1 text-[11px] text-muted hover:bg-hover hover:text-primary"
            >
              <RotateCcw className="h-3 w-3" />
              Retry all failures
            </button>
          )}
          {pending.length > 0 && (
            <button
              type="button"
              onClick={() => setDraining(true)}
              className="flex items-center gap-1 rounded-panel border border-live/50 bg-live/10 px-2 py-1 text-[11px] text-live hover:bg-live/20"
            >
              <Play className="h-3 w-3" />
              Drain queue
            </button>
          )}
          <button
            type="button"
            onClick={() => setEnqueuing(true)}
            className="flex items-center gap-1 rounded-panel border border-accent/60 bg-accent/10 px-2 py-1 text-[11px] text-accent hover:bg-accent/20"
          >
            <Plus className="h-3 w-3" />
            Enqueue task
          </button>
        </div>
      </div>

      {empty ? (
        <EmptyState icon={ListTodo} message="The queue is empty — enqueue a task to fill it." />
      ) : (
        <div className="flex flex-col gap-4 p-4">
          <section>
            <h3 className="mb-1 text-[11px] uppercase tracking-wide text-faint">
              Pending <span className="tabular">({pending.length})</span>
            </h3>
            {pending.length === 0 ? (
              <p className="text-[12px] text-faint">Nothing pending.</p>
            ) : (
              <PendingRows pending={pending} onDelete={setDeleting} />
            )}
          </section>

          <section>
            <h3 className="mb-1 text-[11px] uppercase tracking-wide text-faint">
              Done <span className="tabular">({done.length})</span>
            </h3>
            {done.length === 0 ? (
              <p className="text-[12px] text-faint">No archived tasks.</p>
            ) : (
              <DoneRows done={done} onRetry={(stem) => retry.mutate({ stem })} />
            )}
          </section>
        </div>
      )}

      {enqueuing && (
        <EnqueueDialog
          onClose={() => {
            setEnqueuing(false)
            enqueue.reset()
          }}
          onSubmit={submitEnqueue}
          pending={pending}
          saving={enqueue.isPending}
          error={enqueue.error instanceof ApiError ? enqueue.error.message : null}
        />
      )}

      {draining && <DrainDialog onClose={() => setDraining(false)} />}

      {deleting && (
        <ConfirmDialog
          title="Delete pending task?"
          message="This removes the queued task before it runs."
          confirmLabel="Delete"
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  )
}
