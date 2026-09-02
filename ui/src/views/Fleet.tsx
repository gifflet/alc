// Fleet.tsx — Every unit executing right now, side by side.
//
// ALC already runs work in parallel (tick --concurrency, conduct --parallel,
// explore --variants), each unit in its own worktree. This is the screen where
// that parallelism is visible as parallelism rather than as a list of log files.
import { useState } from 'react'
import { LayoutGrid } from 'lucide-react'
import { api } from '../api/client'
import { useFleet } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { runningExecForStem, useExecState } from '../app/execStore'
import { uiStore } from '../app/uiStore'
import { ConfirmDialog } from '../components/Dialog'
import { EmptyState } from '../components/EmptyState'
import { FleetCard } from '../components/FleetCard'
import { Loading } from '../components/primitives'

export function Fleet() {
  const id = useProjectId()
  const { data, isLoading } = useFleet(id)
  const execState = useExecState()
  const [cancelling, setCancelling] = useState<{ stem: string; execId: string } | null>(null)

  if (isLoading) return <Loading />
  const units = data?.units ?? []

  if (units.length === 0) {
    return (
      <EmptyState
        icon={LayoutGrid}
        message={
          'Nothing running. Dispatch work with `alc run chore "<task>"`, or drain the queue with `alc tick --concurrency 4` to see units here side by side.'
        }
      />
    )
  }

  return (
    <div className="h-full overflow-auto p-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {units.map((unit) => {
          // Cancel used to live ONLY in the Console drawer — invisible on the
          // one screen whose job is watching running agents (finding 37). It
          // now renders INSIDE the card's frame; a confirm naming the run
          // guards the fat finger (a cancel kills a paid engine turn).
          const exec = runningExecForStem(execState, id, unit.stem)
          return (
            <FleetCard
              key={unit.stem}
              unit={unit}
              onOpen={() =>
                uiStore.openTab({ target: { type: 'run', stem: unit.stem }, title: unit.stem })
              }
              onCancel={exec ? () => setCancelling({ stem: unit.stem, execId: exec.id }) : undefined}
            />
          )
        })}
      </div>
      {cancelling && (
        <ConfirmDialog
          title="Cancel this run?"
          message={`${cancelling.stem} — the engine stops; a 30s salvage grace keeps work already written.`}
          confirmLabel="Cancel run"
          cancelLabel="Keep running"
          onConfirm={() => {
            void api.cancelExec(cancelling.execId).catch(() => {})
            setCancelling(null)
          }}
          onCancel={() => setCancelling(null)}
        />
      )}
    </div>
  )
}
