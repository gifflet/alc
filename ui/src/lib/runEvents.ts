// runEvents.ts — Turn a run's JSONL events into the Assurance Loop timeline.
//
// The timeline is the product's identity: for each run a horizontal, segmented
// track of Act -> Verify -> Repair per attempt, with a check dot per check
// (green passed / red failed). This module is the pure model behind that view;
// the <Timeline> component only renders what buildTimeline returns.
//
// Event shapes come straight from the alc control plane (see events.py and the
// emit() call sites in runner/assurance/flow/queue).
import type { RunEvent, Scorecard } from '../api/types'

export interface TimelineCheck {
  name: string
  passed: boolean
}

export interface TimelineAttempt {
  index: number
  /** null while the Act turn is still running (no act_finished yet). */
  actOk: boolean | null
  verifyStarted: boolean
  checks: TimelineCheck[]
}

export type GroupKind = 'mandate' | 'stage'

export interface TimelineGroup {
  label: string
  kind: GroupKind
  /** Blueprint or specialist backing this group, when known. */
  ref?: string
  attempts: TimelineAttempt[]
  /** null while the group is still running. */
  success: boolean | null
}

export interface Timeline {
  kind: 'run' | 'flow' | 'task'
  title: string
  task: string
  engine?: string
  model?: string
  groups: TimelineGroup[]
  scorecard: Scorecard | null
  success: boolean | null
  finished: boolean
  commitSha?: string | null
}

function num(event: RunEvent, key: string): number {
  const v = event[key]
  return typeof v === 'number' ? v : 0
}

function str(event: RunEvent, key: string): string | undefined {
  const v = event[key]
  return typeof v === 'string' ? v : undefined
}

/** Aggregate per-stage scorecards the way the backend aggregates a FlowReport. */
export function aggregateScorecard(
  cards: Scorecard[],
  success: boolean | null,
): Scorecard | null {
  if (cards.length === 0) return null
  return {
    span: cards.reduce((a, c) => a + c.span, 0),
    passes: cards.reduce((a, c) => a + c.passes, 0),
    streak: success === true && cards.every((c) => c.streak === 1) ? 1 : 0,
    touch: cards.reduce((a, c) => a + c.touch, 0),
  }
}

function newAttempt(index: number): TimelineAttempt {
  return { index, actOk: null, verifyStarted: false, checks: [] }
}

function getAttempt(group: TimelineGroup, index: number): TimelineAttempt {
  let a = group.attempts.find((x) => x.index === index)
  if (!a) {
    a = newAttempt(index)
    group.attempts.push(a)
  }
  return a
}

/** Fold a run's events into a Timeline. Tolerant of partial (live) event streams. */
export function buildTimeline(events: RunEvent[]): Timeline {
  const timeline: Timeline = {
    kind: 'run',
    title: '',
    task: '',
    groups: [],
    scorecard: null,
    success: null,
    finished: false,
  }
  const scorecards: Scorecard[] = []
  let current: TimelineGroup | null = null

  const openImplicitMandate = (label: string, ref?: string): TimelineGroup => {
    const group: TimelineGroup = { label, kind: 'mandate', ref, attempts: [], success: null }
    timeline.groups.push(group)
    current = group
    return group
  }

  for (const event of events) {
    switch (event.event) {
      case 'flow_started':
        timeline.kind = 'flow'
        timeline.title = str(event, 'flow') ?? timeline.title
        timeline.task = str(event, 'task') ?? timeline.task
        break

      case 'task_started':
        timeline.kind = 'task'
        timeline.title = str(event, 'name') ?? timeline.title
        timeline.task = str(event, 'task') ?? timeline.task
        break

      case 'mandate_started': {
        const blueprint = str(event, 'blueprint') ?? 'mandate'
        // Top-level bare run: this mandate is the whole run's header.
        if (timeline.kind === 'run' && !timeline.title) {
          timeline.title = blueprint
          timeline.task = str(event, 'task') ?? timeline.task
        }
        timeline.engine = str(event, 'engine') ?? timeline.engine
        timeline.model = str(event, 'model') ?? timeline.model
        // Inside a stage the group already exists; otherwise open an implicit one.
        if (current === null || current.kind !== 'stage') {
          openImplicitMandate(blueprint, blueprint)
        } else if (!current.ref) {
          current.ref = blueprint
        }
        break
      }

      case 'stage_started': {
        const group: TimelineGroup = {
          label: str(event, 'stage') ?? 'stage',
          kind: 'stage',
          ref: str(event, 'blueprint') ?? str(event, 'specialist'),
          attempts: [],
          success: null,
        }
        timeline.groups.push(group)
        current = group
        break
      }

      case 'act_started': {
        const group = current ?? openImplicitMandate(timeline.title || 'mandate')
        getAttempt(group, num(event, 'attempt'))
        break
      }

      case 'act_finished': {
        const group = current ?? openImplicitMandate(timeline.title || 'mandate')
        const attempt = getAttempt(group, num(event, 'attempt'))
        attempt.actOk = event.ok === true
        break
      }

      case 'verify_started': {
        const group = current ?? openImplicitMandate(timeline.title || 'mandate')
        getAttempt(group, num(event, 'attempt')).verifyStarted = true
        break
      }

      case 'check_finished': {
        const group = current ?? openImplicitMandate(timeline.title || 'mandate')
        getAttempt(group, num(event, 'attempt')).checks.push({
          name: str(event, 'name') ?? '',
          passed: event.passed === true,
        })
        break
      }

      case 'mandate_finished': {
        const card = event.scorecard as Scorecard | undefined
        if (card) scorecards.push(card)
        // A top-level mandate closes the whole run; a stage mandate does not
        // (its stage_finished will).
        if (current && current.kind === 'mandate') {
          current.success = event.success === true
          current = null
        }
        if (timeline.kind === 'run') {
          timeline.success = event.success === true
          timeline.finished = true
        }
        break
      }

      case 'stage_finished':
        if (current) current.success = event.success === true
        current = null
        break

      case 'flow_finished':
        timeline.success = event.success === true
        timeline.finished = true
        timeline.commitSha = str(event, 'commit_sha') ?? null
        break

      case 'task_finished':
        timeline.success = event.success === true
        timeline.finished = true
        break

      default:
        break
    }
  }

  timeline.scorecard = aggregateScorecard(scorecards, timeline.success)
  return timeline
}

/** A short, human one-liner for the raw event feed next to the timeline. */
export function describeEvent(event: RunEvent): string {
  switch (event.event) {
    case 'mandate_started':
      return `Mandate — ${str(event, 'blueprint')} · ${str(event, 'engine')}/${str(event, 'model')}`
    case 'act_started':
      return `Act attempt ${num(event, 'attempt') + 1}`
    case 'act_finished':
      return `Act attempt ${num(event, 'attempt') + 1} ${event.ok ? 'ok' : 'failed'}`
    case 'verify_started': {
      const checks = Array.isArray(event.checks) ? event.checks.length : 0
      return `Verify attempt ${num(event, 'attempt') + 1} — ${checks} check${checks === 1 ? '' : 's'}`
    }
    case 'check_started':
      // Emitted as each check begins so a slow/hung check is visible AS it runs.
      return `Check ${str(event, 'name')} running…`
    case 'check_finished':
      return `Check ${str(event, 'name')} ${
        event.timed_out ? 'timed out ⏱' : event.passed ? 'passed' : 'failed'
      }`
    case 'mandate_finished':
      return `Mandate finished — ${event.success ? 'success' : 'failure'}`
    case 'flow_started':
      return `Flow ${str(event, 'flow')} started`
    case 'stage_started':
      return `Stage ${str(event, 'stage')} — ${str(event, 'blueprint') ?? str(event, 'specialist')}`
    case 'stage_finished':
      return `Stage ${str(event, 'stage')} ${event.success ? 'ok' : 'failed'}`
    case 'flow_finished':
      return `Flow finished — ${event.success ? 'success' : 'failure'}`
    case 'task_started':
      return `Task ${str(event, 'name')} (${str(event, 'kind')})`
    case 'task_finished':
      return `Task finished — ${event.success ? 'success' : 'failure'}`
    case 'engine_activity':
      // The engine's granular activity (Bash/Read/Edit/… for claude-code; the
      // model's notes for others) — nested under the macro events so an operator
      // sees WHAT the engine actually did, engine-agnostically.
      return `↳ ${str(event, 'note') ?? 'activity'}`
    default:
      return event.event
  }
}
