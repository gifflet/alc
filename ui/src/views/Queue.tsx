// Queue.tsx — Pending tasks + archived (done) tasks with an expandable report.
import { useState } from 'react'
import { ChevronDown, ChevronRight, ListTodo } from 'lucide-react'
import { useQueue } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { DataTable } from '../components/DataTable'
import type { Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { Loading, Pill } from '../components/primitives'
import { RelativeTime } from '../components/RelativeTime'
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

function DoneRows({ done }: { done: DoneTask[] }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <table className="w-full border-collapse text-[12px]">
      <thead>
        <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-faint">
          <th className="w-6 px-2 py-1" />
          <th className="px-2 py-1 font-medium">Task</th>
          <th className="w-20 px-2 py-1 font-medium">Result</th>
          <th className="w-24 px-2 py-1 font-medium">When</th>
        </tr>
      </thead>
      <tbody>
        {done.map((d) => {
          const open = expanded === d.stem
          const success = d.report?.success ?? null
          return (
            <>
              <tr
                key={d.stem}
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
              </tr>
              {open && d.report && (
                <tr key={`${d.stem}-report`}>
                  <td colSpan={4} className="p-0">
                    <ReportSummary report={d.report} />
                  </td>
                </tr>
              )}
            </>
          )
        })}
      </tbody>
    </table>
  )
}

export function Queue() {
  const id = useProjectId()
  const { data, isLoading } = useQueue(id)

  if (isLoading) return <Loading />
  const pending = data?.pending ?? []
  const done = data?.done ?? []
  if (pending.length === 0 && done.length === 0) {
    return <EmptyState icon={ListTodo} message="The queue is empty — enqueue tasks to fill it." />
  }

  const pendingColumns: Column<PendingTask>[] = [
    { key: 'task', header: 'Task', className: 'text-muted', render: (p) => <span className="truncate">{firstLine(p.task.task)}</span> },
    { key: 'kind', header: 'Kind', className: 'w-20 font-mono text-faint', render: (p) => p.task.kind },
    { key: 'name', header: 'Unit', className: 'w-28 text-muted', render: (p) => p.task.name ?? p.task.flow },
    {
      key: 'isolate',
      header: 'Isolate',
      className: 'w-16',
      render: (p) => (p.task.isolate ? <Pill tone="accent">yes</Pill> : <span className="text-faint">no</span>),
    },
    { key: 'retries', header: 'Retries', className: 'w-16 tabular text-faint', render: (p) => p.task.retries },
    {
      key: 'deps',
      header: 'Depends on',
      className: 'w-28 font-mono text-faint',
      render: (p) => (p.task.depends_on.length ? p.task.depends_on.join(', ') : '—'),
    },
  ]

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <section>
        <h2 className="mb-1 text-[11px] uppercase tracking-wide text-faint">
          Pending <span className="tabular">({pending.length})</span>
        </h2>
        {pending.length === 0 ? (
          <p className="text-[12px] text-faint">Nothing pending.</p>
        ) : (
          <DataTable columns={pendingColumns} rows={pending} rowKey={(p) => p.stem} />
        )}
      </section>

      <section>
        <h2 className="mb-1 text-[11px] uppercase tracking-wide text-faint">
          Done <span className="tabular">({done.length})</span>
        </h2>
        {done.length === 0 ? (
          <p className="text-[12px] text-faint">No archived tasks.</p>
        ) : (
          <DoneRows done={done} />
        )}
      </section>
    </div>
  )
}
