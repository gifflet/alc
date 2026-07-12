// Queue.tsx — Pending tasks + archived (done) tasks with enqueue/retry/delete.
import { Fragment, useState } from 'react'
import { ChevronDown, ChevronRight, ListTodo, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { useDeletePending, useEnqueueTask, useQueue, useRetryQueue } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { ConfirmDialog } from '../components/Dialog'
import { EmptyState } from '../components/EmptyState'
import { Loading, Pill } from '../components/primitives'
import { RelativeTime } from '../components/RelativeTime'
import { EnqueueDialog } from './EnqueueDialog'
import { ApiError } from '../api/client'
import type { DoneTask, FlowReport, PendingTask } from '../api/types'

function firstLine(text: string): string {
  return text.split('\n')[0]
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
                onClick={() => setExpanded(open ? null : d.stem)}
                className="h-[28px] cursor-pointer border-b border-border/60 transition-colors duration-120 hover:bg-hover"
              >
                <td className="px-2">
                  {d.report ? (
                    open ? (
                      <ChevronDown className="h-3.5 w-3.5 text-faint" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 text-faint" />
                    )
                  ) : null}
                </td>
                <td className="truncate px-2 text-muted">
                  {d.task ? firstLine(d.task.task) : d.stem}
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
              {open && d.report && (
                <tr>
                  <td colSpan={5} className="p-0">
                    <ReportSummary report={d.report} />
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
  return (
    <table className="w-full border-collapse text-[12px]">
      <thead>
        <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-faint">
          <th className="px-2 py-1 font-medium">Task</th>
          <th className="w-20 px-2 py-1 font-medium">Kind</th>
          <th className="w-28 px-2 py-1 font-medium">Unit</th>
          <th className="w-16 px-2 py-1 font-medium">Isolate</th>
          <th className="w-28 px-2 py-1 font-medium">Depends on</th>
          <th className="w-10 px-2 py-1 font-medium" />
        </tr>
      </thead>
      <tbody>
        {pending.map((p) => (
          <tr key={p.stem} className="group h-[28px] border-b border-border/60 hover:bg-hover">
            <td className="truncate px-2 text-muted">{firstLine(p.task.task)}</td>
            <td className="px-2 font-mono text-faint">{p.task.kind}</td>
            <td className="px-2 text-muted">{p.task.name ?? p.task.flow}</td>
            <td className="px-2">
              {p.task.isolate ? <Pill tone="accent">yes</Pill> : <span className="text-faint">no</span>}
            </td>
            <td className="px-2 font-mono text-faint">
              {p.task.depends_on.length ? p.task.depends_on.join(', ') : '—'}
            </td>
            <td className="px-2">
              <button
                type="button"
                aria-label={`Delete ${p.stem}`}
                onClick={() => onDelete(p.stem)}
                className="flex h-4 w-4 items-center justify-center text-faint opacity-0 transition-opacity duration-120 hover:text-error group-hover:opacity-100"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </td>
          </tr>
        ))}
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
