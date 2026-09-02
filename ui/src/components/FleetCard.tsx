// FleetCard.tsx — One unit executing right now.
//
// The card folds the unit's raw events with buildTimeline — the SAME pure model
// RunDetail uses, so the two screens can never disagree about what phase a run
// is in. Nothing about phase/attempt/check is computed in the backend.
import { Radio, Square } from 'lucide-react'
import { ActionButton } from './ActionButton'
import { buildTimeline } from '../lib/runEvents'
import type { FleetUnit } from '../api/types'
import { StatusDot } from './StatusDot'
import { RelativeTime } from './RelativeTime'

/** Act -> Verify -> Repair: the phase the newest attempt is in. */
export type Phase = 'act' | 'verify' | 'repair' | 'done'

export interface FleetCardState {
  title: string
  task: string
  unit: string
  phase: Phase
  /** 1-based for display: attempt 0 is "attempt 1" to an operator. */
  attempt: number
  runningCheck: string | null
  engine?: string
  model?: string
}

/**
 * Derive what the card shows from a (possibly partial) event stream.
 *
 * Pure and exported so the mapping is unit-tested without rendering: the phase
 * rules are the subtle part, and they must match what the timeline shows.
 */
export function cardState(unit: FleetUnit): FleetCardState {
  const timeline = buildTimeline(unit.events)
  const group = timeline.groups[timeline.groups.length - 1]
  const attempt = group?.attempts[group.attempts.length - 1]

  let phase: Phase = 'act'
  if (timeline.finished) phase = 'done'
  else if (attempt?.verifyStarted) phase = 'verify'
  else if (attempt && attempt.index > 0) phase = 'repair'

  // A check with no verdict yet is the one currently executing. check_finished
  // appends a verdict, so the running check is the last STARTED without a result
  // — which the timeline models as "verify started, checks so far < expected".
  const runningCheck = phase === 'verify' ? (lastCheckName(unit) ?? null) : null

  return {
    title: timeline.title || unit.stem,
    task: timeline.task,
    unit: group?.ref ?? group?.label ?? unit.kind,
    phase,
    attempt: (attempt?.index ?? 0) + 1,
    runningCheck,
    engine: timeline.engine,
    model: timeline.model,
  }
}

/** The most recent check_started without a matching check_finished. */
function lastCheckName(unit: FleetUnit): string | undefined {
  let running: string | undefined
  for (const event of unit.events) {
    if (event.event === 'check_started' && typeof event.name === 'string') running = event.name
    if (event.event === 'check_finished') running = undefined
  }
  return running
}

const PHASE_LABEL: Record<Phase, string> = {
  act: 'Act',
  verify: 'Verify',
  repair: 'Repair',
  done: 'Finished',
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-[length:var(--ui-text-label)] font-medium uppercase tracking-[0.06em] text-faint">
        {label}
      </span>
      <span className="min-w-0 truncate text-[length:var(--ui-text-title)] text-muted">{value}</span>
    </div>
  )
}

export function FleetCard({
  unit,
  onOpen,
  onCancel,
}: {
  unit: FleetUnit
  onOpen: () => void
  /** Cancel THIS unit's running exec. Rendered as a footer INSIDE the card's
   * frame — a sibling below the border read as "cancel one or all?"
   * (dogfood round 10). Absent -> no footer at all. */
  onCancel?: () => void
}) {
  const state = cardState(unit)
  const running = state.phase !== 'done'

  return (
    // Stretched-overlay pattern: the card was ONE <button>, which made any
    // inner control illegal HTML and exiled Cancel below the frame. The card
    // is an <article> now; an invisible full-bleed button behind the content
    // keeps tap-anywhere-to-open, and Cancel is a real sibling INSIDE the
    // ring — scope readable from containment alone.
    <article className="group relative flex w-full flex-col gap-3 rounded-[var(--radius-md)] bg-raised p-4 text-left shadow-[var(--elev-1)] ring-1 ring-border/40 transition-all duration-120 hover:ring-border hover:shadow-[var(--elev-2)] has-[:focus-visible]:ring-accent">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Open run ${state.title}`}
        className="absolute inset-0 z-0 rounded-[inherit] focus-visible:outline-none"
      />
      <div className="pointer-events-none relative z-10 flex min-w-0 items-center gap-2.5">
        <StatusDot tone={running ? 'running' : 'idle'} pulse={running} />
        <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-primary">
          {state.title}
        </span>
        <span className="shrink-0 text-[length:var(--ui-text-body)] text-faint">
          <RelativeTime value={unit.mtime} />
        </span>
      </div>

      {state.task && (
        <p className="pointer-events-none relative z-10 line-clamp-2 text-[length:var(--ui-text-title)] leading-[1.5] text-muted">{state.task}</p>
      )}

      <div className="pointer-events-none relative z-10 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border/40 pt-3">
        <Field label="phase" value={`${PHASE_LABEL[state.phase]} · attempt ${state.attempt}`} />
        <Field label="unit" value={state.unit} />
        {state.runningCheck && <Field label="check" value={state.runningCheck} />}
        {state.engine && (
          <Field label="engine" value={state.model ? `${state.engine}/${state.model}` : state.engine} />
        )}
      </div>

      {unit.truncated && (
        <span className="pointer-events-none relative z-10 text-[length:var(--ui-text-body)] text-faint">log truncated — showing the newest events</span>
      )}
      {onCancel && (
        <div className="relative z-10 -mx-4 -mb-4 flex items-center justify-between gap-3 rounded-b-[inherit] border-t border-border/40 bg-base/40 px-4 py-2">
          {/* The stem printed beside the button is the second of three scope
              signals (containment, name, singular label). */}
          <span className="pointer-events-none truncate font-mono text-[length:var(--ui-text-label)] text-faint">
            {unit.stem}
          </span>
          <ActionButton
            aria-label={`Cancel run ${unit.stem}`}
            tone="error"
            size="sm"
            onClick={onCancel}
            className="shrink-0"
          >
            <Square className="h-3 w-3" />
            Cancel run
          </ActionButton>
        </div>
      )}
    </article>
  )
}

export const FleetIcon = Radio
