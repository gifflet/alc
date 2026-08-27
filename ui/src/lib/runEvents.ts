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
  /** A quarantined check runs and its failure is recorded, but it does not block
   *  success. Without this the timeline shows a failed check inside a successful
   *  run and leaves the reader to guess why. */
  quarantined: boolean
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
  /** True when the run was interrupted (a terminal `run_aborted` event) — a
   * definitive abort, distinct from the transient "stale" guess in RunDetail. */
  aborted: boolean
  commitSha?: string | null
  /** The `alc/*` branch the isolated work committed on, when the run was
   * isolated and actually changed something. Null otherwise — the run either ran
   * against the working tree or made no change worth committing. */
  branch?: string | null
  /** True when the run was a spike — the one fenced relaxation of the checks
   *  gate. Its verdict is not the guarantee a real demand's verdict is. */
  spike?: boolean
  /** Check-defining files (`"path (reason)"`) the run's net diff touched — the
   * always-on tamper-evidence (check_config_edited events). Empty when clean. */
  checkConfigEdits: string[]
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
    aborted: false,
    checkConfigEdits: [],
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
        if (event.spike === true) timeline.spike = true
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
            quarantined: event.quarantined === true,
        })
        break
      }

      case 'check_config_edited': {
        // Always-on tamper-evidence: the run's net diff touched check-defining
        // config. Accumulate across stages (each stage mandate may emit one).
        const files = Array.isArray(event.files)
          ? event.files.filter((f): f is string => typeof f === 'string')
          : []
        timeline.checkConfigEdits.push(...files)
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

      case 'isolation_finished':
        // Emitted after the worktree exits, so it always arrives last.
        // `committed` false means nothing changed — no branch to point at.
        timeline.branch = event.committed === true ? (str(event, 'branch') ?? null) : null
        break

      case 'run_aborted':
        // Interrupted (Ctrl-C / SIGTERM). Terminal for ANY kind — bare mandate,
        // flow, or task — mirroring the backend (runs._run_finished). Leaves
        // `success` as-is: an abort is neither a pass nor a check failure.
        timeline.finished = true
        timeline.aborted = true
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
    case 'check_config_edited': {
      const files = Array.isArray(event.files) ? event.files.filter((f) => typeof f === 'string') : []
      return `modified check config: ${files.join(', ')}`
    }
    case 'env_refresh_started': {
      // env-refresh reinstalls deps before the checks when a manifest changed;
      // `command` is the install argv (path as a fallback when it is absent).
      const cmd = Array.isArray(event.command)
        ? event.command.filter((c): c is string => typeof c === 'string').join(' ')
        : str(event, 'path')
      return `Env refresh — ${cmd ?? ''} running…`
    }
    case 'env_refresh_finished':
      // No `command` on finish; carries ok / timed_out / duration_s. A timed-out
      // refresh is surfaced distinctly from a plain failure, like check_finished.
      return `Env refresh (${str(event, 'path') ?? ''}) ${
        event.timed_out ? 'timed out ⏱' : event.ok ? 'ok' : 'failed'
      } (${num(event, 'duration_s').toFixed(1)}s)`
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
    case 'isolation_finished':
      return event.committed === true
        ? `Committed on ${str(event, 'branch')}`
        : 'Nothing changed — no branch created'
    case 'run_aborted':
      return `aborted — ${str(event, 'reason') ?? 'interrupted'}`
    case 'engine_activity':
      // The engine's granular activity (Bash/Read/Edit/… for claude-code; the
      // model's notes for others) — nested under the macro events so an operator
      // sees WHAT the engine actually did, engine-agnostically.
      return `↳ ${str(event, 'note') ?? 'activity'}`
    default:
      return event.event
  }
}

/** Names of checks that FAILED but were quarantined, from the run's last attempt.
 *
 * A run can report success with a failed check in its log — that is the whole
 * point of quarantine. Saying "your checks passed" without naming them is the
 * one thing the UI must not do, so the verdict reads this and qualifies itself.
 * Only the last attempt counts: an earlier attempt's failure was repaired.
 */
export function quarantinedFailures(timeline: Timeline): string[] {
  const attempts = timeline.groups.flatMap((g) => g.attempts)
  const last = attempts[attempts.length - 1]
  if (!last) return []
  return last.checks.filter((c) => !c.passed && c.quarantined).map((c) => c.name)
}
