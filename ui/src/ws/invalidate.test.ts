import { describe, expect, it } from 'vitest'
import { wsInvalidations } from './invalidate'
import { keys } from '../api/keys'

describe('wsInvalidations', () => {
  it('invalidates the project list on a global change', () => {
    expect(wsInvalidations({ type: 'project_list_changed', project_id: null })).toEqual([
      keys.projects(),
    ])
  })

  it('invalidates queue + scorecard when a report is archived', () => {
    const out = wsInvalidations({ type: 'report_added', project_id: 'p', stem: 's' })
    expect(out).toContainEqual(keys.queue('p'))
    expect(out).toContainEqual(keys.scorecard('p'))
  })

  it('invalidates queue on queue_changed', () => {
    expect(wsInvalidations({ type: 'queue_changed', project_id: 'p' })).toEqual([keys.queue('p')])
  })

  it('invalidates a loop state, ledger and the loops collection', () => {
    const out = wsInvalidations({ type: 'loop_changed', project_id: 'p', name: 'nightly' })
    expect(out).toContainEqual(keys.loopState('p', 'nightly'))
    expect(out).toContainEqual(keys.loopLedger('p', 'nightly'))
    expect(out).toContainEqual(keys.collection('p', 'loops'))
  })

  it('invalidates the manifest and lint when the manifest changes', () => {
    const out = wsInvalidations({ type: 'config_changed', project_id: 'p', resource: 'manifest' })
    expect(out).toContainEqual(keys.manifest('p'))
    expect(out).toContainEqual(keys.lint('p'))
  })

  it('invalidates a collection and lint when a blueprint changes', () => {
    const out = wsInvalidations({
      type: 'config_changed',
      project_id: 'p',
      resource: 'blueprints',
    })
    expect(out).toContainEqual(keys.collection('p', 'blueprints'))
    expect(out).toContainEqual(keys.lint('p'))
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
    expect(midRun).toEqual([])
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
})
