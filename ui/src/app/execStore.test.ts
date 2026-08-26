import { beforeEach, describe, expect, it } from 'vitest'
import { execStore } from './execStore'
import type { ExecView } from '../api/types'

beforeEach(() => execStore.reset())

describe('execStore', () => {
  it('launches an exec, appends output, and finishes it', () => {
    execStore.launch({ id: 'e1', projectId: 'p', command: 'run' })
    expect(execStore.getState().selectedId).toBe('e1')

    execStore.output({ execId: 'e1', projectId: 'p', line: 'hello' })
    execStore.output({ execId: 'e1', projectId: 'p', line: 'world' })
    execStore.finished({ execId: 'e1', exitCode: 0 })

    const ex = execStore.getState().execs[0]
    expect(ex.lines).toEqual(['hello', 'world'])
    expect(ex.status).toBe('finished')
    expect(ex.exitCode).toBe(0)
  })

  it('marks a non-zero exit as error', () => {
    execStore.launch({ id: 'e1', projectId: 'p', command: 'run' })
    execStore.finished({ execId: 'e1', exitCode: 2 })
    expect(execStore.getState().execs[0].status).toBe('error')
  })

  it('tracks multiple execs running concurrently and routes output by id', () => {
    // A second exec starts while the first is still running — no guard blocks it.
    execStore.launch({ id: 'e1', projectId: 'p', command: 'loop' })
    execStore.launch({ id: 'e2', projectId: 'p', command: 'run' })

    execStore.output({ execId: 'e1', projectId: 'p', line: 'loop line' })
    execStore.output({ execId: 'e2', projectId: 'p', line: 'run line' })

    const { execs } = execStore.getState()
    expect(execs).toHaveLength(2)
    expect(execs.every((e) => e.status === 'running')).toBe(true)
    expect(execs.find((e) => e.id === 'e1')!.lines).toEqual(['loop line'])
    expect(execs.find((e) => e.id === 'e2')!.lines).toEqual(['run line'])
  })

  it('adopts an exec created early by streamed output', () => {
    execStore.output({ execId: 'e1', projectId: 'p', line: 'first' })
    execStore.launch({ id: 'e1', projectId: 'p', command: 'flow' })

    expect(execStore.getState().execs).toHaveLength(1)
    const ex = execStore.getState().execs[0]
    expect(ex.command).toBe('flow')
    expect(ex.lines).toEqual(['first'])
  })

  it('attaches a run to the latest running exec of its project only', () => {
    execStore.launch({ id: 'e1', projectId: 'p', command: 'run' })
    execStore.noteRun('p', 'run-123')
    execStore.noteRun('p', 'run-123') // idempotent
    execStore.noteRun('other', 'run-x') // no running exec for this project

    expect(execStore.getState().execs[0].runStems).toEqual(['run-123'])
  })

  it('still attaches a run that surfaces just after the exec finished (fast runs)', () => {
    execStore.launch({ id: 'e1', projectId: 'p', command: 'run' })
    execStore.finished({ execId: 'e1', exitCode: 0 })
    // run_event lands a beat after exec_finished; within the grace window it binds.
    execStore.noteRun('p', 'run-late')

    expect(execStore.getState().execs[0].runStems).toEqual(['run-late'])
  })

  it('clears output and removes an exec, reselecting a neighbour', () => {
    execStore.launch({ id: 'e1', projectId: 'p', command: 'run' })
    execStore.launch({ id: 'e2', projectId: 'p', command: 'flow' })
    execStore.output({ execId: 'e1', projectId: 'p', line: 'x' })

    execStore.clear('e1')
    expect(execStore.getState().execs.find((e) => e.id === 'e1')!.lines).toEqual([])

    execStore.select('e2')
    execStore.remove('e2')
    expect(execStore.getState().execs).toHaveLength(1)
    expect(execStore.getState().selectedId).toBe('e1')
  })

  it('seeds unknown execs from the server and keeps local live lines', () => {
    execStore.launch({ id: 'e1', projectId: 'p', command: 'run' })
    execStore.output({ execId: 'e1', projectId: 'p', line: 'live' })

    const views: ExecView[] = [
      { id: 'e1', project_id: 'p', command: 'run', status: 'finished', exit_code: 0, output: ['stale'] },
      { id: 'e2', project_id: 'p', command: 'tick', status: 'running', exit_code: null, output: ['a', 'b'] },
    ]
    execStore.seed(views)

    const e1 = execStore.getState().execs.find((e) => e.id === 'e1')!
    const e2 = execStore.getState().execs.find((e) => e.id === 'e2')!
    expect(e1.lines).toEqual(['live']) // local output preserved
    expect(e1.status).toBe('finished') // server status adopted
    expect(e2.lines).toEqual(['a', 'b']) // recovered from server
    expect(e2.status).toBe('running')
  })
})

describe('execs that belong to no project', () => {
  it('are not seeded into the store', () => {
    // A clone runs before any project exists and is followed by the component
    // that started it. Seeding it here would create an entry that byProject and
    // noteRun can never reach, since both compare against a concrete id.
    execStore.reset()
    execStore.seed([
      {
        id: 'clone-1',
        project_id: null,
        command: 'git clone https://h/o/r.git',
        status: 'running',
        exit_code: null,
        output: [],
      },
      {
        id: 'run-1',
        project_id: 'p1',
        command: 'alc run chore',
        status: 'running',
        exit_code: null,
        output: [],
      },
    ])

    expect(execStore.getState().execs.map((e) => e.id)).toEqual(['run-1'])
  })
})
