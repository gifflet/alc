// Runs.tsx — The runs list; a row opens the run detail in a tab.
import { Radio } from 'lucide-react'
import { useRuns } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { uiStore, useUiState } from '../app/uiStore'
import { DataTable } from '../components/DataTable'
import type { Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/primitives'
import { RelativeTime } from '../components/RelativeTime'
import { StatusDot } from '../components/StatusDot'
import { formatBytes } from '../lib/format'
import type { RunSummary } from '../api/types'

type RunState = 'finished' | 'stale' | 'live'

/** A finished run closed with its terminal event; a stale run is unfinished but
 * its log has gone quiet past the interrupted threshold (no live process); a
 * live run is unfinished and still being written. */
function runState(r: RunSummary): RunState {
  if (r.finished) return 'finished'
  return r.stale ? 'stale' : 'live'
}

export function Runs() {
  const id = useProjectId()
  const { activeTabId } = useUiState()
  const { data, isLoading } = useRuns(id)
  const runs = data?.runs ?? []

  if (isLoading) return <Loading />
  if (runs.length === 0) {
    return (
      <EmptyState
        icon={Radio}
        message={'No runs yet — dispatch one with `alc run chore "<task>"` (or the Run button on a Blueprint) to see it here live.'}
      />
    )
  }

  const columns: Column<RunSummary>[] = [
    {
      key: 'status',
      header: '',
      className: 'w-6',
      render: (r) => {
        const s = runState(r)
        return (
          <StatusDot
            tone={s === 'finished' ? 'idle' : s === 'stale' ? 'warn' : 'running'}
            pulse={s === 'live'}
            title={s === 'stale' ? 'interrupted — no live process is writing this run' : undefined}
          />
        )
      },
    },
    { key: 'kind', header: 'Kind', className: 'w-16 font-mono text-faint', render: (r) => r.kind },
    {
      key: 'stem',
      header: 'Run',
      className: 'font-mono text-muted',
      render: (r) => <span className="truncate">{r.stem}</span>,
    },
    {
      key: 'state',
      header: 'State',
      className: 'w-20',
      render: (r) => {
        const s = runState(r)
        const cls =
          s === 'finished' ? 'text-faint' : s === 'stale' ? 'text-warn' : 'text-running'
        return <span className={cls}>{s}</span>
      },
    },
    { key: 'size', header: 'Size', className: 'w-20 tabular text-faint', render: (r) => formatBytes(r.size) },
    { key: 'when', header: 'When', className: 'w-24', render: (r) => <RelativeTime value={r.mtime} /> },
  ]

  return (
    <div className="h-full overflow-auto">
      <DataTable
        columns={columns}
        rows={runs}
        rowKey={(r) => r.stem}
        activeKey={activeTabId?.startsWith('run:') ? activeTabId.slice('run:'.length) : undefined}
        onRowClick={(r) => uiStore.openTab({ target: { type: 'run', stem: r.stem }, title: r.stem })}
      />
    </div>
  )
}
