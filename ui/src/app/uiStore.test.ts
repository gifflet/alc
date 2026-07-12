import { beforeEach, describe, expect, it } from 'vitest'
import { tabId, uiStore } from './uiStore'
import type { TabTarget } from './uiStore'

const runTab: TabTarget = { type: 'run', stem: 'abc' }
const sourceTab: TabTarget = { type: 'source', resource: 'blueprints', name: 'chore' }

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

describe('tabId', () => {
  it('is stable and unique per target', () => {
    expect(tabId(runTab)).toBe('run:abc')
    expect(tabId(sourceTab)).toBe('source:blueprints:chore')
    expect(tabId({ type: 'view', view: 'dashboard' })).toBe('view:dashboard')
  })
})

describe('tabs', () => {
  it('opens a tab and makes it active', () => {
    uiStore.openTab({ target: runTab, title: 'abc' })
    const s = uiStore.getState()
    expect(s.tabs).toHaveLength(1)
    expect(s.activeTabId).toBe('run:abc')
  })

  it('does not duplicate an already-open tab, just focuses it', () => {
    uiStore.openTab({ target: runTab, title: 'abc' })
    uiStore.openTab({ target: sourceTab, title: 'chore' })
    uiStore.openTab({ target: runTab, title: 'abc' })
    const s = uiStore.getState()
    expect(s.tabs).toHaveLength(2)
    expect(s.activeTabId).toBe('run:abc')
  })

  it('closes a tab and activates a neighbour', () => {
    uiStore.openTab({ target: runTab, title: 'abc' })
    uiStore.openTab({ target: sourceTab, title: 'chore' })
    uiStore.closeTab('source:blueprints:chore')
    const s = uiStore.getState()
    expect(s.tabs).toHaveLength(1)
    expect(s.activeTabId).toBe('run:abc')
  })

  it('clears the active id when the last tab closes', () => {
    uiStore.openTab({ target: runTab, title: 'abc' })
    uiStore.closeTab('run:abc')
    expect(uiStore.getState().activeTabId).toBeNull()
  })
})

describe('panels', () => {
  it('toggles the left tool window collapsed flag', () => {
    const before = uiStore.getState().leftCollapsed
    uiStore.toggleLeft()
    expect(uiStore.getState().leftCollapsed).toBe(!before)
  })

  it('persists panel sizing to localStorage', () => {
    uiStore.setLeftWidth(320)
    uiStore.setBottomTab('problems')
    const raw = localStorage.getItem('alc-ui:panels')
    expect(raw).not.toBeNull()
    const saved = JSON.parse(raw as string)
    expect(saved.leftWidth).toBe(320)
    expect(saved.bottomTab).toBe('problems')
  })

  it('clamps the left width to sane bounds', () => {
    uiStore.setLeftWidth(9000)
    expect(uiStore.getState().leftWidth).toBeLessThanOrEqual(600)
    uiStore.setLeftWidth(10)
    expect(uiStore.getState().leftWidth).toBeGreaterThanOrEqual(160)
  })
})

describe('subscribe', () => {
  it('notifies subscribers on change', () => {
    let calls = 0
    const unsub = uiStore.subscribe(() => {
      calls += 1
    })
    uiStore.openTab({ target: runTab, title: 'abc' })
    expect(calls).toBe(1)
    unsub()
    uiStore.openTab({ target: sourceTab, title: 'chore' })
    expect(calls).toBe(1)
  })
})
