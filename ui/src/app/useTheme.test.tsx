import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { resolveTheme, useApplyTheme } from './useTheme'
import { uiStore } from './uiStore'
import { clearMatchMedia, mockMatchMedia } from '../test/utils'

function Probe() {
  return <span data-testid="theme">{useApplyTheme()}</span>
}

beforeEach(() => uiStore.setTheme(null))
afterEach(() => {
  clearMatchMedia()
  uiStore.setTheme(null)
  delete document.documentElement.dataset.theme
})

describe('resolveTheme', () => {
  it('follows the OS when the operator has not chosen', () => {
    expect(resolveTheme(null, true)).toBe('light')
    expect(resolveTheme(null, false)).toBe('dark')
  })

  it('lets an explicit choice win in both directions', () => {
    expect(resolveTheme('dark', true)).toBe('dark')
    expect(resolveTheme('light', false)).toBe('light')
  })
})

describe('useApplyTheme', () => {
  it('falls back to dark on a host with no matchMedia', () => {
    clearMatchMedia()
    const { getByTestId } = render(<Probe />)
    expect(getByTestId('theme')).toHaveTextContent('dark')
  })

  it('applies the OS preference', () => {
    mockMatchMedia(['prefers-color-scheme: light'])
    const { getByTestId } = render(<Probe />)
    expect(getByTestId('theme')).toHaveTextContent('light')
  })

  it('writes the theme onto the document element', () => {
    mockMatchMedia(['prefers-color-scheme: light'])
    render(<Probe />)
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('honours the operator override over the OS', () => {
    mockMatchMedia(['prefers-color-scheme: light'])
    uiStore.setTheme('dark')
    const { getByTestId } = render(<Probe />)
    expect(getByTestId('theme')).toHaveTextContent('dark')
  })

  it('persists the choice across a store reload', () => {
    uiStore.setTheme('light')
    expect(JSON.parse(localStorage.getItem('alc-ui:panels')!).theme).toBe('light')
  })

  it('tolerates panel state saved before the theme field existed', () => {
    // An operator upgrading has a persisted blob with no `theme` key; it must
    // load as "follow the OS", not crash or force a theme.
    localStorage.setItem(
      'alc-ui:panels',
      JSON.stringify({ leftWidth: 240, leftCollapsed: false, bottomHeight: 200, bottomCollapsed: true, bottomTab: 'console' }),
    )
    uiStore.reset()
    expect(uiStore.getState().theme).toBeNull()
    mockMatchMedia(['prefers-color-scheme: light'])
    const { getByTestId } = render(<Probe />)
    expect(getByTestId('theme')).toHaveTextContent('light')
  })
})
