import { describe, expect, it } from 'vitest'
import { aggregateScorecard, buildTimeline, describeEvent } from './runEvents'
import type { RunEvent } from '../api/types'

// A real single-mandate run (captured from the demo backend).
const MANDATE_RUN: RunEvent[] = [
  { ts: 't0', event: 'mandate_started', blueprint: 'chore', task: 'exec via API', engine: 'mock', model: 'mock-small' },
  { ts: 't1', event: 'act_started', attempt: 0 },
  { ts: 't2', event: 'act_finished', attempt: 0, ok: true },
  { ts: 't3', event: 'verify_started', attempt: 0, checks: ['smoke'] },
  { ts: 't4', event: 'check_finished', attempt: 0, name: 'smoke', passed: true, output_tail: '' },
  { ts: 't5', event: 'mandate_finished', success: true, attempts: 1, scorecard: { span: 1, passes: 1, streak: 1, touch: 0 } },
]

describe('buildTimeline — single mandate', () => {
  it('detects a run kind and its header', () => {
    const t = buildTimeline(MANDATE_RUN)
    expect(t.kind).toBe('run')
    expect(t.title).toBe('chore')
    expect(t.task).toBe('exec via API')
    expect(t.engine).toBe('mock')
    expect(t.model).toBe('mock-small')
  })

  it('builds one group with one passing attempt', () => {
    const t = buildTimeline(MANDATE_RUN)
    expect(t.groups).toHaveLength(1)
    const g = t.groups[0]
    expect(g.attempts).toHaveLength(1)
    expect(g.attempts[0].actOk).toBe(true)
    expect(g.attempts[0].checks).toEqual([{ name: 'smoke', passed: true }])
    expect(g.success).toBe(true)
  })

  it('marks the run finished and carries the final scorecard', () => {
    const t = buildTimeline(MANDATE_RUN)
    expect(t.finished).toBe(true)
    expect(t.success).toBe(true)
    expect(t.scorecard).toEqual({ span: 1, passes: 1, streak: 1, touch: 0 })
  })
})

describe('buildTimeline — repair loop', () => {
  const events: RunEvent[] = [
    { ts: 't0', event: 'mandate_started', blueprint: 'bug', task: 'fix', engine: 'mock', model: 'm' },
    { ts: 't1', event: 'act_started', attempt: 0 },
    { ts: 't2', event: 'act_finished', attempt: 0, ok: true },
    { ts: 't3', event: 'verify_started', attempt: 0, checks: ['pytest'] },
    { ts: 't4', event: 'check_finished', attempt: 0, name: 'pytest', passed: false, output_tail: 'E' },
    { ts: 't5', event: 'act_started', attempt: 1 },
    { ts: 't6', event: 'act_finished', attempt: 1, ok: true },
    { ts: 't7', event: 'verify_started', attempt: 1, checks: ['pytest'] },
    { ts: 't8', event: 'check_finished', attempt: 1, name: 'pytest', passed: true, output_tail: '' },
    { ts: 't9', event: 'mandate_finished', success: true, attempts: 2, scorecard: { span: 1, passes: 2, streak: 0, touch: 0 } },
  ]

  it('records two attempts, the first failing a check', () => {
    const t = buildTimeline(events)
    const g = t.groups[0]
    expect(g.attempts).toHaveLength(2)
    expect(g.attempts[0].checks[0].passed).toBe(false)
    expect(g.attempts[1].checks[0].passed).toBe(true)
  })
})

describe('buildTimeline — live run (no terminal event)', () => {
  const events: RunEvent[] = [
    { ts: 't0', event: 'mandate_started', blueprint: 'chore', task: 'x', engine: 'mock', model: 'm' },
    { ts: 't1', event: 'act_started', attempt: 0 },
  ]
  it('is not finished and the attempt act is still pending', () => {
    const t = buildTimeline(events)
    expect(t.finished).toBe(false)
    expect(t.success).toBeNull()
    expect(t.groups[0].attempts[0].actOk).toBeNull()
  })
})

describe('buildTimeline — flow with stages', () => {
  const events: RunEvent[] = [
    { ts: 't0', event: 'flow_started', flow: 'ship', task: 'build', stages: ['impl', 'gate'] },
    { ts: 't1', event: 'stage_started', stage: 'impl', blueprint: 'feature' },
    { ts: 't2', event: 'act_started', attempt: 0 },
    { ts: 't3', event: 'act_finished', attempt: 0, ok: true },
    { ts: 't4', event: 'verify_started', attempt: 0, checks: ['pytest'] },
    { ts: 't5', event: 'check_finished', attempt: 0, name: 'pytest', passed: true, output_tail: '' },
    { ts: 't6', event: 'mandate_finished', success: true, attempts: 1, scorecard: { span: 1, passes: 1, streak: 1, touch: 0 } },
    { ts: 't7', event: 'stage_finished', stage: 'impl', success: true },
    { ts: 't8', event: 'stage_started', stage: 'gate', blueprint: 'feature' },
    { ts: 't9', event: 'mandate_finished', success: true, attempts: 1, scorecard: { span: 2, passes: 0, streak: 1, touch: 0 } },
    { ts: 't10', event: 'stage_finished', stage: 'gate', success: true },
    { ts: 't11', event: 'flow_finished', success: true, commit_sha: 'abc123' },
  ]

  it('is a flow with one group per stage', () => {
    const t = buildTimeline(events)
    expect(t.kind).toBe('flow')
    expect(t.title).toBe('ship')
    expect(t.groups.map((g) => g.label)).toEqual(['impl', 'gate'])
    expect(t.groups[0].success).toBe(true)
    expect(t.finished).toBe(true)
    expect(t.commitSha).toBe('abc123')
  })

  it('aggregates the per-stage scorecards', () => {
    const t = buildTimeline(events)
    expect(t.scorecard).toEqual({ span: 3, passes: 1, streak: 1, touch: 0 })
  })
})

describe('buildTimeline — run_aborted (interrupted run)', () => {
  it('folds a run_aborted event into finished + aborted, leaving success null', () => {
    const events: RunEvent[] = [
      { ts: 't0', event: 'mandate_started', blueprint: 'chore', task: 'x', engine: 'mock', model: 'm' },
      { ts: 't1', event: 'act_started', attempt: 0 },
      { ts: 't2', event: 'run_aborted', reason: 'interrupted' },
    ]
    const t = buildTimeline(events)
    expect(t.finished).toBe(true)
    expect(t.aborted).toBe(true)
    expect(t.success).toBeNull()
  })

  it('is terminal for a flow run too (no flow_finished needed)', () => {
    const events: RunEvent[] = [
      { ts: 't0', event: 'flow_started', flow: 'ship', task: 'build' },
      { ts: 't1', event: 'stage_started', stage: 'impl', blueprint: 'feature' },
      { ts: 't2', event: 'run_aborted', reason: 'terminated' },
    ]
    const t = buildTimeline(events)
    expect(t.finished).toBe(true)
    expect(t.aborted).toBe(true)
  })

  it('is not aborted for a normally finished run', () => {
    expect(buildTimeline(MANDATE_RUN).aborted).toBe(false)
  })
})

describe('buildTimeline — check_config_edited (tamper-evidence)', () => {
  it('folds the touched files onto checkConfigEdits', () => {
    const events: RunEvent[] = [
      ...MANDATE_RUN.slice(0, 5),
      { ts: 't4b', event: 'check_config_edited', files: ['eslint.config.mjs (check config)'] },
      { ts: 't5', event: 'mandate_finished', success: true, attempts: 1, scorecard: { span: 1, passes: 1, streak: 1, touch: 0 } },
    ]
    const t = buildTimeline(events)
    expect(t.checkConfigEdits).toEqual(['eslint.config.mjs (check config)'])
  })

  it('is empty when no such event was emitted', () => {
    expect(buildTimeline(MANDATE_RUN).checkConfigEdits).toEqual([])
  })
})

describe('aggregateScorecard', () => {
  it('returns null with no cards', () => {
    expect(aggregateScorecard([], true)).toBeNull()
  })
  it('sums span/passes and clears streak on failure', () => {
    const cards = [
      { span: 1, passes: 1, streak: 1, touch: 0 },
      { span: 2, passes: 3, streak: 1, touch: 0 },
    ]
    expect(aggregateScorecard(cards, false)).toEqual({ span: 3, passes: 4, streak: 0, touch: 0 })
  })
})

describe('describeEvent', () => {
  it('labels a mandate start', () => {
    expect(describeEvent(MANDATE_RUN[0])).toContain('chore')
  })
  it('labels a passing check', () => {
    expect(describeEvent(MANDATE_RUN[4])).toContain('smoke')
  })
  it('nests engine activity (tool uses) under the macro events', () => {
    const label = describeEvent({ ts: 't', event: 'engine_activity', note: 'Bash: grep -rn STEPS .' })
    expect(label).toBe('↳ Bash: grep -rn STEPS .')
  })
  it('labels a running check so a hang is attributable', () => {
    expect(describeEvent({ ts: 't', event: 'check_started', name: 'test' })).toBe('Check test running…')
  })
  it('surfaces a timed-out check distinctly from a plain failure', () => {
    const timedOut = describeEvent({ ts: 't', event: 'check_finished', name: 'test', passed: false, timed_out: true })
    expect(timedOut).toBe('Check test timed out ⏱')
    const failed = describeEvent({ ts: 't', event: 'check_finished', name: 'test', passed: false })
    expect(failed).toBe('Check test failed')
  })
  it('labels a check-config edit with the touched files', () => {
    const label = describeEvent({ ts: 't', event: 'check_config_edited', files: ['ruff.toml (check config)'] })
    expect(label).toBe('modified check config: ruff.toml (check config)')
  })
  it('labels an env-refresh start with the running install command', () => {
    const label = describeEvent({ ts: 't', event: 'env_refresh_started', path: 'ui', command: ['npm', 'install'] })
    expect(label).toContain('npm install')
  })
  it('labels a finished env-refresh with ok and its duration', () => {
    const label = describeEvent({
      ts: 't', event: 'env_refresh_finished', path: 'ui', ok: true, duration_s: 14.83, exit_code: 0, timed_out: false,
    })
    expect(label).toContain('ok')
    expect(label).toContain('(14.8s)')
  })
  it('surfaces a timed-out env-refresh distinctly from a plain failure', () => {
    const label = describeEvent({
      ts: 't', event: 'env_refresh_finished', path: 'ui', ok: false, duration_s: 900, timed_out: true,
    })
    expect(label).toContain('timed out')
  })
  it('labels a failed env-refresh', () => {
    const label = describeEvent({
      ts: 't', event: 'env_refresh_finished', path: 'ui', ok: false, duration_s: 2.1, exit_code: 1, timed_out: false,
    })
    expect(label).toContain('failed')
  })
  it('labels an aborted run with its reason', () => {
    expect(describeEvent({ ts: 't', event: 'run_aborted', reason: 'interrupted' })).toBe('aborted — interrupted')
    // Falls back to "interrupted" when no reason is carried.
    expect(describeEvent({ ts: 't', event: 'run_aborted' })).toBe('aborted — interrupted')
  })
})

describe('isolation_finished', () => {
  it('records the branch the isolated work committed on', () => {
    const t = buildTimeline([
      { ts: '1', event: 'mandate_started', blueprint: 'chore' },
      { ts: '2', event: 'mandate_finished', success: true },
      { ts: '3', event: 'isolation_finished', committed: true, branch: 'alc/run-ab12cd34' },
    ])
    expect(t.branch).toBe('alc/run-ab12cd34')
  })

  it('records no branch when nothing changed', () => {
    // committed:false is "there was nothing to commit", not "look elsewhere".
    const t = buildTimeline([
      { ts: '1', event: 'mandate_started', blueprint: 'chore' },
      { ts: '2', event: 'isolation_finished', committed: false, branch: null },
    ])
    expect(t.branch).toBeNull()
  })
})
