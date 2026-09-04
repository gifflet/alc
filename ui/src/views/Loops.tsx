// Loops.tsx — The loops list; a row opens its state + ledger in a tab.
import { useState } from 'react'
import { Play, RefreshCw, Repeat } from 'lucide-react'
import { ApiError } from '../api/client'
import { useCollection, useLoopState, useWorktreeStatus } from '../api/hooks'
import { useProjectId } from '../app/ProjectContext'
import { useExecState } from '../app/execStore'
import { uiStore, useUiState } from '../app/uiStore'
import { useStartExec } from '../app/useStartExec'
import { ActionButton } from '../components/ActionButton'
import { ConfirmDialog } from '../components/Dialog'
import { EmptyState } from '../components/EmptyState'
import { Loading, Pill } from '../components/primitives'
import { StatusDot } from '../components/StatusDot'
import type { Tone } from '../components/StatusDot'
import type { LoopState, LoopStatus } from '../api/types'
import { LoopRunDialog } from './LoopRunDialog'

/** "plans via janitor · stops after 10 cycles or $10" — the row explains what
 * a tap would spend and when it would stop, for an operator who has never
 * opened the YAML (finding 41). */
function describeLoop(definition: LoopState['definition']): string | null {
  if (!definition) return null
  const parts: string[] = []
  if (definition.replenish_kind) {
    parts.push(
      definition.replenish_ref
        ? `${definition.replenish_kind} via ${definition.replenish_ref}`
        : definition.replenish_kind,
    )
  } else {
    parts.push('drain-only')
  }
  const stops = [`${definition.max_cycles} cycles`]
  if (definition.budget_max != null) {
    stops.push(
      definition.budget_unit === 'usd'
        ? `$${definition.budget_max}`
        : `${definition.budget_max} ${definition.budget_unit ?? ''}`.trim(),
    )
  }
  parts.push(`stops after ${stops.join(' or ')}`)
  return parts.join(' · ')
}

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
  const [confirmingCycle, setConfirmingCycle] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const summary = describeLoop(data?.definition ?? null)

  // Surface a rejected cycle dispatch instead of swallowing it: the run proceeds
  // on a dirty tree, but a serial committing demand can still abort itself at the
  // flow level — that error (and any other exec failure) must not vanish on click,
  // so we render it below the row rather than the silent `.catch(() => {})` that
  // once made a blocked run look like a no-op.
  const runCycle = async () => {
    setError(null)
    setNotice(null)
    try {
      await start('cycle', { name })
      // The loop's state file only updates BETWEEN cycles, so the row cannot
      // flip to "running" by itself — without a receipt the tap read as a
      // no-op and invited a paid double-tap (finding 41).
      setNotice('Cycle started — watch it live in the Console or Fleet.')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to start.')
    }
  }

  return (
    <div className="border-b border-border/15">
      <div
        className={`group flex h-[var(--ui-row-h)] w-full items-center gap-2 px-3 text-[length:var(--ui-text-body)] transition-colors duration-120 ${
          active ? 'bg-hover' : 'hover:bg-hover'
        }`}
      >
        <StatusDot tone={STATUS_TONE[status]} pulse={status === 'running'} />
        <button
          type="button"
          onClick={() => uiStore.openTab({ target: { type: 'loop', name }, title: name })}
          // h-full, not just flex-1: the ROW is --ui-row-h (48px on a coarse
          // pointer) but the button only spanned its text, so the tap target was
          // 22px inside a 48px row a thumb is aiming at. Same shape as the Hire
          // buttons that lost their padding — the visual size and the hit area
          // have to be the same thing.
          className="flex h-full min-w-0 flex-1 items-center gap-2 truncate text-left text-muted"
        >
          <span className="min-w-0 flex-1 truncate">{name}</span>
        </button>
        <Pill tone={STATUS_TONE[status]}>{status}</Pill>
        <span className="tabular w-16 text-right text-[length:var(--ui-text-label)] text-faint">cycle {data?.cycle ?? 0}</span>
      </div>
      {/* Second line: what the loop DOES, and two LABELED spend controls —
          the icon-only ▷/⟳ pair reproduced the cycle/loop naming collision as
          two anonymous buttons, one of which starts a budget-capped multi-
          cycle run (finding 41). Engine-spending controls never hide behind
          hover-reveal. */}
      <div className="flex flex-wrap items-center gap-2 px-3 pb-2">
        {summary && (
          <span className="min-w-0 flex-1 truncate text-[length:var(--ui-text-label)] text-faint">
            {summary}
          </span>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <ActionButton
            aria-label={`Run one cycle of ${name}`}
            tone="ghost"
            size="sm"
            onClick={() => setConfirmingCycle(true)}
          >
            <Play className="h-3 w-3" />
            Run once
          </ActionButton>
          <ActionButton
            aria-label={`Run loop ${name}`}
            tone="accent"
            size="sm"
            onClick={() => setRunning(true)}
          >
            <Repeat className="h-3 w-3" />
            Run loop
          </ActionButton>
        </div>
      </div>
      {running && <LoopRunDialog name={name} onClose={() => setRunning(false)} />}
      {confirmingCycle && (
        <ConfirmDialog
          title={`Run one cycle of ${name}?`}
          message={
            `One cycle plans new work and drains it — real engine turns are spent.` +
            (summary ? ` This loop: ${summary}.` : '')
          }
          confirmLabel="Run cycle"
          cancelLabel="Not now"
          tone="accent"
          onConfirm={() => {
            setConfirmingCycle(false)
            void runCycle()
          }}
          onCancel={() => setConfirmingCycle(false)}
        />
      )}
      {error && <p className="px-3 pb-1 text-[length:var(--ui-text-label)] text-error">{error}</p>}
      {notice && !error && (
        <p role="status" className="px-3 pb-1 text-[length:var(--ui-text-label)] text-muted">
          {notice}
        </p>
      )}
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
  // The loop STATE file only updates between cycles, so during a cycle the rows
  // sit frozen at their pre-cycle values — twenty silent seconds into an $8
  // cycle the screen still said "PENDING cycle 0" (finding 41). The exec store
  // knows better: say a cycle/loop is executing while one is.
  const execState = useExecState()
  const cycleLive = execState.execs.some(
    (e) => e.status === 'running' && e.projectId === id && (e.command === 'cycle' || e.command === 'loop'),
  )

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
          className="m-2 rounded-panel border border-warn/40 bg-warn/10 px-3 py-2 text-[length:var(--ui-text-body)] text-warn"
        >
          {DIRTY_NOTE}
        </div>
      )}
      {cycleLive && (
        <div
          role="status"
          className="m-2 rounded-panel border border-live/40 bg-live/10 px-3 py-2 text-[length:var(--ui-text-body)] text-live"
        >
          A cycle is executing — watch it live in the Console or Fleet. Loop rows update
          when the cycle completes.
        </div>
      )}
      {loops.map((l) => (
        <LoopRow key={l.name} name={l.name} />
      ))}
    </div>
  )
}
