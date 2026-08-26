import { describe, expect, it } from 'vitest'
import { wsInvalidations } from './invalidate'
import { keys } from '../api/keys'

describe('wsInvalidations', () => {
  it('invalidates the project list on a global change', () => {
    expect(wsInvalidations({ type: 'project_list_changed', project_id: null })).toEqual([
      keys.projects(),
    ])
  })

  it('invalidates queue, scorecard, metrics, audit, branches and worktree when a report is archived', () => {
    const out = wsInvalidations({ type: 'report_added', project_id: 'p', stem: 's' })
    expect(out).toContainEqual(keys.queue('p'))
    expect(out).toContainEqual(keys.scorecard('p'))
    expect(out).toContainEqual(keys.metrics('p'))
    expect(out).toContainEqual(keys.audit('p'))
    expect(out).toContainEqual(keys.branches('p'))
    // A finished run commits the workdir as it goes — the tree's dirty state may
    // have flipped, so Loops' run-block gate must re-check.
    expect(out).toContainEqual(keys.worktree('p'))
  })

  it('invalidates queue on queue_changed', () => {
    // A queue change can create or resolve an outstanding failure, so the
    // Inbox (and its badge) must follow it.
    expect(wsInvalidations({ type: 'queue_changed', project_id: 'p' })).toEqual([
      keys.queue('p'),
      keys.inbox('p'),
    ])
  })

  it('invalidates a loop state, ledger, the loops collection and the team roster', () => {
    const out = wsInvalidations({ type: 'loop_changed', project_id: 'p', name: 'nightly' })
    expect(out).toContainEqual(keys.loopState('p', 'nightly'))
    expect(out).toContainEqual(keys.loopLedger('p', 'nightly'))
    expect(out).toContainEqual(keys.collection('p', 'loops'))
    expect(out).toContainEqual(keys.team('p'))
  })

  it('invalidates the manifest, lint, the checks audit and the onboard proposal when the manifest changes', () => {
    const out = wsInvalidations({ type: 'config_changed', project_id: 'p', resource: 'manifest' })
    expect(out).toContainEqual(keys.manifest('p'))
    expect(out).toContainEqual(keys.lint('p'))
    // A check_sets edit changes the audit — the Checks view must refresh live.
    expect(out).toContainEqual(keys.checksAudit('p'))
    // It also changes the onboard proposal (the `project` set may now exist).
    expect(out).toContainEqual(keys.onboardAll('p'))
    // A config edit is a natural moment to re-check the tree — keep Loops' run-block honest.
    expect(out).toContainEqual(keys.worktree('p'))
  })

  it('invalidates a collection, lint, the team roster, the checks audit and the onboard proposal when a blueprint changes', () => {
    const out = wsInvalidations({
      type: 'config_changed',
      project_id: 'p',
      resource: 'blueprints',
    })
    expect(out).toContainEqual(keys.collection('p', 'blueprints'))
    expect(out).toContainEqual(keys.lint('p'))
    expect(out).toContainEqual(keys.team('p'))
    // A check_set opt-in / checks edit changes the audit — Checks must refresh live.
    expect(out).toContainEqual(keys.checksAudit('p'))
    // The opt-in also drops that blueprint from the onboard candidates.
    expect(out).toContainEqual(keys.onboardAll('p'))
    // A collection change is a natural moment to re-check the tree — keep Loops' run-block honest.
    expect(out).toContainEqual(keys.worktree('p'))
  })

  it('invalidates the runs list only on lifecycle boundaries', () => {
    const started = wsInvalidations({
      type: 'run_event',
      project_id: 'p',
      stem: 's',
      event: { ts: 't', event: 'mandate_started' },
    })
    expect(started).toContainEqual(keys.runs('p'))

    const midRun = wsInvalidations({
      type: 'run_event',
      project_id: 'p',
      stem: 's',
      event: { ts: 't', event: 'check_finished' },
    })
    // The runs LIST must not thrash on mid-run events...
    expect(midRun).not.toContainEqual(keys.runs('p'))
    // ...but the Fleet grid shows phase/attempt/running check, so it follows
    // every event — that live motion is the entire point of the screen.
    expect(midRun).toEqual([keys.fleet('p')])
  })

  it('keeps the fleet live on both mid-run and lifecycle events', () => {
    for (const event of ['mandate_started', 'act_finished', 'mandate_finished']) {
      const out = wsInvalidations({
        type: 'run_event',
        project_id: 'p',
        stem: 's',
        event: { ts: 't', event },
      })
      expect(out).toContainEqual(keys.fleet('p'))
    }
  })

  it('invalidates the run-configs list when the file changes', () => {
    expect(wsInvalidations({ type: 'run_configs_changed', project_id: 'p' })).toEqual([
      keys.runConfigs('p'),
    ])
  })

  it('invalidates execs on exec output', () => {
    expect(
      wsInvalidations({
        type: 'exec_output',
        project_id: 'p',
        exec_id: 'e',
        stream: 'stdout',
        line: 'x',
      }),
    ).toEqual([keys.execs()])
  })

  it('invalidates signals on signals_changed', () => {
    expect(wsInvalidations({ type: 'signals_changed', project_id: 'p' })).toEqual([
      keys.signals('p'),
    ])
  })

  it('invalidates the worktree query on a live worktree_changed push', () => {
    expect(
      wsInvalidations({
        type: 'worktree_changed',
        project_id: 'p',
        status: {
          available: true,
          dirty: true,
          branch: 'main',
          detached: false,
          upstream: 'origin/main',
          ahead: 1,
          behind: 0,
          untracked: 2,
        },
      }),
    ).toEqual([keys.worktree('p')])
  })

  it('invalidates execs, variants and branches when an exec finishes', () => {
    const out = wsInvalidations({
      type: 'exec_finished',
      project_id: 'p',
      exec_id: 'e',
      exit_code: 0,
    })
    expect(out).toContainEqual(keys.execs())
    expect(out).toContainEqual(keys.variants('p'))
    expect(out).toContainEqual(keys.branches('p'))
  })
})
