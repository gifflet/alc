// Timeline.tsx — The Assurance Loop timeline: Act -> Verify -> Repair per attempt.
//
// For each group (a bare mandate, or one stage of a flow) it draws a horizontal
// segmented track: an Act/Repair phase pill per attempt, followed by a check dot
// per check (green passed, red failed). A still-running attempt pulses amber.
import { ChevronRight } from 'lucide-react'
import type { Timeline, TimelineAttempt, TimelineGroup } from '../lib/runEvents'
import { formatElapsed } from '../lib/runEvents'
import { StatusDot } from './StatusDot'
import type { Tone } from './StatusDot'

function groupTone(g: TimelineGroup): Tone {
  if (g.success === true) return 'live'
  if (g.success === false) return 'error'
  return 'running'
}

function actClasses(a: TimelineAttempt): string {
  if (a.actOk === true) return 'border-live/60 text-live'
  if (a.actOk === false) return 'border-error/60 text-error'
  return 'border-running/60 text-running alc-pulse'
}

function AttemptTrack({ attempt }: { attempt: TimelineAttempt }) {
  const phase = attempt.index === 0 ? 'Act' : `Repair ${attempt.index}`
  return (
    <div className="flex items-center gap-1.5">
      {attempt.index > 0 && <ChevronRight className="h-3 w-3 text-faint" />}
      <span
        className={`rounded-[3px] border px-1.5 py-0.5 font-mono text-[length:var(--ui-text-label)] uppercase tracking-wide ${actClasses(
          attempt,
        )}`}
      >
        {phase}
      </span>
      {attempt.verifyStarted && (
        <span className="font-mono text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">verify</span>
      )}
      {attempt.checks.length > 0 && (
        <span className="flex items-center gap-1">
          {attempt.checks.map((c, i) => (
            <StatusDot
              key={`${c.name}-${i}`}
              tone={c.passed ? 'live' : 'error'}
              title={`${c.name}: ${c.passed ? 'passed' : 'failed'} (${formatElapsed(c.durationS)})`}
            />
          ))}
        </span>
      )}
    </div>
  )
}

function GroupRow({ group }: { group: TimelineGroup }) {
  return (
    <div className="flex items-start gap-3 py-1.5">
      <div className="w-32 shrink-0">
        <div className="flex items-center gap-1.5 truncate text-[length:var(--ui-text-body)] text-primary">
          <StatusDot tone={groupTone(group)} pulse={group.success === null} />
          <span className="truncate">{group.label}</span>
        </div>
        {group.ref && group.ref !== group.label && (
          <div className="truncate pl-3.5 text-[length:var(--ui-text-label)] text-faint">{group.ref}</div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {group.attempts.length === 0 ? (
          <span className="font-mono text-[length:var(--ui-text-label)] uppercase tracking-wide text-faint">waiting</span>
        ) : (
          group.attempts.map((a) => <AttemptTrack key={a.index} attempt={a} />)
        )}
      </div>
    </div>
  )
}

export function TimelineView({ timeline }: { timeline: Timeline }) {
  return (
    <div className="divide-y divide-border/50 rounded-panel border border-border bg-raised px-3 py-1">
      {timeline.groups.map((g, i) => (
        <GroupRow key={`${g.label}-${i}`} group={g} />
      ))}
    </div>
  )
}
