// Loops.tsx — The loops list; a row opens its state + ledger in a tab.
import { RefreshCw } from 'lucide-react'
import { useCollection, useLoopState } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { uiStore, useUiState } from '../app/uiStore'
import { EmptyState } from '../components/EmptyState'
import { Loading, Pill } from '../components/primitives'
import { StatusDot } from '../components/StatusDot'
import type { Tone } from '../components/StatusDot'
import type { LoopStatus } from '../api/types'

const STATUS_TONE: Record<LoopStatus, Tone> = {
  pending: 'idle',
  running: 'running',
  stopped: 'error',
}

function LoopRow({ name }: { name: string }) {
  const id = useProjectId()
  const { activeTabId } = useUiState()
  const { data } = useLoopState(id, name)
  const status = data?.status ?? 'pending'
  const active = activeTabId === `loop:${name}`
  return (
    <button
      type="button"
      onClick={() => uiStore.openTab({ target: { type: 'loop', name }, title: name })}
      className={`flex h-[28px] w-full items-center gap-2 border-b border-border/60 px-3 text-left text-[12px] transition-colors duration-120 ${
        active ? 'bg-hover' : 'hover:bg-hover'
      }`}
    >
      <StatusDot tone={STATUS_TONE[status]} pulse={status === 'running'} />
      <span className="min-w-0 flex-1 truncate text-muted">{name}</span>
      <Pill tone={STATUS_TONE[status]}>{status}</Pill>
      <span className="tabular w-16 text-right text-[11px] text-faint">cycle {data?.cycle ?? 0}</span>
    </button>
  )
}

export function Loops() {
  const id = useProjectId()
  const { data, isLoading } = useCollection(id, 'loops')

  if (isLoading) return <Loading />
  const loops = data ?? []
  if (loops.length === 0) {
    return <EmptyState icon={RefreshCw} message="No loops defined in this project." />
  }
  return (
    <div className="h-full overflow-auto">
      {loops.map((l) => (
        <LoopRow key={l.name} name={l.name} />
      ))}
    </div>
  )
}
