// Loops.tsx — The loops list; a row opens its state + ledger in a tab.
import { useState } from 'react'
import { Play, RefreshCw, Repeat } from 'lucide-react'
import { ApiError } from '../api/client'
import { useCollection, useLoopState, useWorktreeStatus } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { uiStore, useUiState } from '../app/uiStore'
import { useStartExec } from '../app/useStartExec'
import { EmptyState } from '../components/EmptyState'
import { Loading, Pill } from '../components/primitives'
import { StatusDot } from '../components/StatusDot'
import type { Tone } from '../components/StatusDot'
import type { LoopStatus } from '../api/types'
import { LoopRunDialog } from './LoopRunDialog'

const STATUS_TONE: Record<LoopStatus, Tone> = {
  pending: 'idle',
  running: 'running',
  stopped: 'error',
}

// A reassuring notice, not a gate: an autonomous run is SAFE on a dirty tree —
// it commits only what it produces, never the operator's own uncommitted work.
// So we set expectations rather than block. Serial committing demands still need
// a clean tree (they abort themselves if not), which is why we nudge toward an
// isolated drain. Mirrors the CLI's warn-and-proceed notice.
const DIRTY_NOTE =
  'Working tree not clean — the run proceeds and commits only what it produces, ' +
  'never your uncommitted work (outside .alc/). Serial committing demands still ' +
  'need a clean tree; prefer an isolated drain.'

function LoopRow({ name }: { name: string }) {
  const id = useProjectId()
  const { activeTabId } = useUiState()
  const start = useStartExec()
  const { data } = useLoopState(id, name)
  const status = data?.status ?? 'pending'
  const active = activeTabId === `loop:${name}`
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Surface a rejected cycle dispatch instead of swallowing it: the run proceeds
  // on a dirty tree, but a serial committing demand can still abort itself at the
  // flow level — that error (and any other exec failure) must not vanish on click,
  // so we render it below the row rather than the silent `.catch(() => {})` that
  // once made a blocked run look like a no-op.
  const runCycle = async () => {
    setError(null)
    try {
      await start('cycle', { name })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to start.')
    }
  }

  return (
    <div className="border-b border-border/60">
      <div
        className={`group flex h-[28px] w-full items-center gap-2 px-3 text-[12px] transition-colors duration-120 ${
          active ? 'bg-hover' : 'hover:bg-hover'
        }`}
      >
        <StatusDot tone={STATUS_TONE[status]} pulse={status === 'running'} />
        <button
          type="button"
          onClick={() => uiStore.openTab({ target: { type: 'loop', name }, title: name })}
          className="flex min-w-0 flex-1 items-center gap-2 truncate text-left text-muted"
        >
          <span className="min-w-0 flex-1 truncate">{name}</span>
        </button>
        <Pill tone={STATUS_TONE[status]}>{status}</Pill>
        <span className="tabular w-16 text-right text-[11px] text-faint">cycle {data?.cycle ?? 0}</span>
        <button
          type="button"
          aria-label={`Run cycle ${name}`}
          onClick={() => void runCycle()}
          className="flex h-4 w-4 items-center justify-center text-faint opacity-0 transition-opacity duration-120 hover:text-live group-hover:opacity-100 disabled:cursor-not-allowed disabled:text-faint disabled:hover:text-faint"
        >
          <Play className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label={`Run loop ${name}`}
          onClick={() => setRunning(true)}
          className="flex h-4 w-4 items-center justify-center text-faint opacity-0 transition-opacity duration-120 hover:text-live group-hover:opacity-100 disabled:cursor-not-allowed disabled:text-faint disabled:hover:text-faint"
        >
          <Repeat className="h-3.5 w-3.5" />
        </button>
        {running && <LoopRunDialog name={name} onClose={() => setRunning(false)} />}
      </div>
      {error && <p className="px-3 pb-1 text-[11px] text-error">{error}</p>}
    </div>
  )
}

export function Loops() {
  const id = useProjectId()
  const { data, isLoading } = useCollection(id, 'loops')
  // A dirty working tree is safe to run on, so we only warn: show a banner that
  // sets expectations, but never gate the run controls. Off-git (or still loading)
  // reads as clean — there is simply nothing to notice.
  const dirty = useWorktreeStatus(id).data?.dirty ?? false

  if (isLoading) return <Loading />
  const loops = data ?? []
  if (loops.length === 0) {
    return <EmptyState icon={RefreshCw} message="No loops defined in this project." />
  }
  return (
    <div className="h-full overflow-auto">
      {dirty && (
        <div
          role="note"
          className="m-2 rounded-panel border border-warn/40 bg-warn/10 px-3 py-2 text-[12px] text-warn"
        >
          {DIRTY_NOTE}
        </div>
      )}
      {loops.map((l) => (
        <LoopRow key={l.name} name={l.name} />
      ))}
    </div>
  )
}
