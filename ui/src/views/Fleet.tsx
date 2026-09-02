// Fleet.tsx — Every unit executing right now, side by side.
//
// ALC already runs work in parallel (tick --concurrency, conduct --parallel,
// explore --variants), each unit in its own worktree. This is the screen where
// that parallelism is visible as parallelism rather than as a list of log files.
import { LayoutGrid, Square } from 'lucide-react'
import { api } from '../api/client'
import { useFleet } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { runningExecForStem, useExecState } from '../app/execStore'
import { uiStore } from '../app/uiStore'
import { ActionButton } from '../components/ActionButton'
import { EmptyState } from '../components/EmptyState'
import { FleetCard } from '../components/FleetCard'
import { Loading } from '../components/primitives'

export function Fleet() {
  const id = useProjectId()
  const { data, isLoading } = useFleet(id)
  const execState = useExecState()

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
          // one screen whose job is watching running agents (finding 37).
          const exec = runningExecForStem(execState, id, unit.stem)
          return (
            <div key={unit.stem} className="flex flex-col gap-1.5">
              <FleetCard
                unit={unit}
                onOpen={() =>
                  uiStore.openTab({ target: { type: 'run', stem: unit.stem }, title: unit.stem })
                }
              />
              {exec && (
                <div className="flex justify-end">
                  <ActionButton
                    aria-label={`Cancel ${unit.stem}`}
                    tone="error"
                    size="sm"
                    onClick={() => void api.cancelExec(exec.id).catch(() => {})}
                  >
                    <Square className="h-3 w-3" />
                    Cancel
                  </ActionButton>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
