import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { useShortcuts } from './useShortcuts'
import { uiStore } from './uiStore'

function Harness({ onHelp = () => {} }: { onHelp?: () => void }) {
  useShortcuts(onHelp)
  return <div />
}

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
})

describe('useShortcuts', () => {
  it('opens a primary view on mod+number', () => {
    render(<Harness />)
    fireEvent.keyDown(window, { key: '2', ctrlKey: true })
    expect(uiStore.getState().activeTabId).toBe('view:queue')
  })

  it('toggles the bottom panel on mod+j', () => {
    render(<Harness />)
    const before = uiStore.getState().bottomCollapsed
    fireEvent.keyDown(window, { key: 'j', metaKey: true })
    expect(uiStore.getState().bottomCollapsed).toBe(!before)
  })

  it('opens the help panel on ?', () => {
    const onHelp = vi.fn()
    render(<Harness onHelp={onHelp} />)
    fireEvent.keyDown(window, { key: '?' })
    expect(onHelp).toHaveBeenCalledOnce()
  })

  it('closes the active closable tab on mod+w but leaves views', () => {
    uiStore.openTab({ target: { type: 'view', view: 'runs' }, title: 'Runs', closable: false })
    uiStore.openTab({ target: { type: 'run', stem: 'abc' }, title: 'abc' })
    render(<Harness />)

    fireEvent.keyDown(window, { key: 'w', metaKey: true })
    expect(uiStore.getState().tabs.map((t) => t.id)).not.toContain('run:abc')

    // The remaining view tab is non-closable — mod+w is a no-op.
    fireEvent.keyDown(window, { key: 'w', metaKey: true })
    expect(uiStore.getState().tabs.map((t) => t.id)).toContain('view:runs')
  })
})
