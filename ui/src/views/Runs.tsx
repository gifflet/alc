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
      header: 'State',
      className: 'w-24',
      priority: 1,
      // Dot AND word in one cell: a separate State column repeated this, and a
      // dot on its own would make colour the only carrier of meaning.
      render: (r) => {
        const s = runState(r)
        const cls = s === 'finished' ? 'text-faint' : s === 'stale' ? 'text-warn' : 'text-running'
        return (
          <span className="flex items-center gap-2">
            <StatusDot
              tone={s === 'finished' ? 'idle' : s === 'stale' ? 'warn' : 'running'}
              pulse={s === 'live'}
              title={s === 'stale' ? 'interrupted — no live process is writing this run' : undefined}
            />
            <span className={cls}>{s}</span>
          </span>
        )
      },
    },
    { key: 'kind', header: 'Kind', className: 'w-16 font-mono text-faint', priority: 2, render: (r) => r.kind },
    {
      key: 'stem',
      header: 'Run',
      // max-w-0 + w-full is the classic table truncation trick: without it the
      // cell sizes to its content and a long stem pushes `When` off-screen —
      // measured on an emulated iPad, where the column simply vanished.
      className: 'w-full max-w-0',
      priority: 1,
      // The stem is an ADDRESS (timestamp + kind + slug + uid). What an operator
      // scans for is what the run was asked to do, so the task leads and the
      // stem sits under it as the identifier you would paste into `alc runs`.
      render: (r) => (
        <span className="flex min-w-0 flex-col justify-center leading-tight">
          <span className="truncate text-primary">{r.title || r.stem}</span>
          {r.title && (
            <span className="truncate font-mono text-[length:var(--ui-text-label)] text-faint">
              {r.unit ? `${r.unit} · ` : ''}
              {r.stem}
            </span>
          )}
        </span>
      ),
    },
    // nowrap: "8m ago" wrapped to two lines once the Run column started
    // claiming the slack (seen on an emulated iPad).
    {
      key: 'when',
      header: 'When',
      className: 'w-24 whitespace-nowrap',
      priority: 2,
      render: (r) => <RelativeTime value={r.mtime} />,
    },
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
