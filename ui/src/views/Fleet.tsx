// Fleet.tsx — Every unit executing right now, side by side.
//
// ALC already runs work in parallel (tick --concurrency, conduct --parallel,
// explore --variants), each unit in its own worktree. This is the screen where
// that parallelism is visible as parallelism rather than as a list of log files.
import { LayoutGrid } from 'lucide-react'
import { useFleet } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { uiStore } from '../app/uiStore'
import { EmptyState } from '../components/EmptyState'
import { FleetCard } from '../components/FleetCard'
import { Loading } from '../components/primitives'

export function Fleet() {
  const id = useProjectId()
  const { data, isLoading } = useFleet(id)

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
        {units.map((unit) => (
          <FleetCard
            key={unit.stem}
            unit={unit}
            onOpen={() =>
              uiStore.openTab({ target: { type: 'run', stem: unit.stem }, title: unit.stem })
            }
          />
        ))}
      </div>
    </div>
  )
}
