import { describe, expect, it } from 'vitest'
import { openArgFromPath, pathForTab, sourceTitle } from './tabRoute'
import type { TabTarget } from './uiStore'

const ID = 'demo'

/** Every target should survive a path → parse round-trip. */
const cases: TabTarget[] = [
  { type: 'view', view: 'dashboard' },
  { type: 'view', view: 'queue' },
  { type: 'view', view: 'runs' },
  { type: 'view', view: 'loops' },
  { type: 'view', view: 'conduct' },
  { type: 'run', stem: '20260712T0359-run-chore-x' },
  { type: 'loop', name: 'nightly' },
  { type: 'source', resource: 'manifest', name: 'manifest' },
  { type: 'source', resource: 'blueprints', name: 'chore' },
  { type: 'source', resource: 'flows', name: 'ship' },
  { type: 'source', resource: 'specialists', name: 'reviewer' },
  { type: 'source', resource: 'loops', name: 'nightly' },
  { type: 'source', resource: 'primers', name: 'trim' },
  { type: 'source', resource: 'prompts', name: 'act' },
]

describe('pathForTab', () => {
  it('maps the dashboard view to the bare project path', () => {
    expect(pathForTab(ID, { type: 'view', view: 'dashboard' })).toBe('/projects/demo')
  })

  it('maps a run to /runs/:stem and a loop to /loops/:name', () => {
    expect(pathForTab(ID, { type: 'run', stem: 'abc' })).toBe('/projects/demo/runs/abc')
    expect(pathForTab(ID, { type: 'loop', name: 'nightly' })).toBe('/projects/demo/loops/nightly')
  })

  it('nests config sources under /config to avoid the loop-view collision', () => {
    expect(pathForTab(ID, { type: 'source', resource: 'manifest', name: 'manifest' })).toBe(
      '/projects/demo/config/manifest',
    )
    expect(pathForTab(ID, { type: 'source', resource: 'loops', name: 'nightly' })).toBe(
      '/projects/demo/config/loops/nightly',
    )
  })
})

describe('openArgFromPath', () => {
  it('round-trips every tab target through its path', () => {
    for (const target of cases) {
      const path = pathForTab(ID, target)
      const segments = path.replace(`/projects/${ID}`, '').split('/').filter(Boolean)
      const arg = openArgFromPath(segments)
      expect(arg?.target).toEqual(target)
    }
  })

  it('treats an empty path and an explicit /dashboard as the dashboard view', () => {
    expect(openArgFromPath([])?.target).toEqual({ type: 'view', view: 'dashboard' })
    expect(openArgFromPath(['dashboard'])?.target).toEqual({ type: 'view', view: 'dashboard' })
  })

  it('marks primary view tabs as non-closable and leaves others closable', () => {
    expect(openArgFromPath(['queue'])?.closable).toBe(false)
    // Run/loop/source tabs omit the flag; openTab defaults them to closable.
    expect(openArgFromPath(['runs', 'abc'])?.closable).not.toBe(false)
  })

  it('returns null for an unknown path', () => {
    expect(openArgFromPath(['nope'])).toBeNull()
    expect(openArgFromPath(['config', 'bogus', 'x'])).toBeNull()
  })

  it('decodes percent-encoded names', () => {
    const arg = openArgFromPath(['runs', encodeURIComponent('a b')])
    expect(arg?.target).toEqual({ type: 'run', stem: 'a b' })
  })
})

describe('sourceTitle', () => {
  it('suffixes each resource with its file extension', () => {
    expect(sourceTitle('manifest', 'manifest')).toBe('manifest.yaml')
    expect(sourceTitle('blueprints', 'chore')).toBe('chore.md')
    expect(sourceTitle('flows', 'ship')).toBe('ship.yaml')
    expect(sourceTitle('prompts', 'act')).toBe('act.md')
  })
})
