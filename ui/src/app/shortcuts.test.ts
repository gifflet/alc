import { describe, expect, it } from 'vitest'
import { resolveShortcut } from './shortcuts'

const key = (over: Partial<KeyboardEvent>): KeyboardEvent =>
  ({ key: '', metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...over }) as KeyboardEvent

describe('resolveShortcut', () => {
  it('maps mod+1..8 to the primary views', () => {
    expect(resolveShortcut(key({ key: '1', metaKey: true }))).toEqual({ type: 'view', view: 'dashboard' })
    expect(resolveShortcut(key({ key: '3', ctrlKey: true }))).toEqual({ type: 'view', view: 'runs' })
    expect(resolveShortcut(key({ key: '5', metaKey: true }))).toEqual({ type: 'view', view: 'conduct' })
    expect(resolveShortcut(key({ key: '6', metaKey: true }))).toEqual({ type: 'view', view: 'team' })
    expect(resolveShortcut(key({ key: '7', metaKey: true }))).toEqual({ type: 'view', view: 'metrics' })
    expect(resolveShortcut(key({ key: '8', metaKey: true }))).toEqual({ type: 'view', view: 'compare' })
  })

  it('maps mod+w/j/b to tab + panel actions', () => {
    expect(resolveShortcut(key({ key: 'w', metaKey: true }))).toEqual({ type: 'close-tab' })
    expect(resolveShortcut(key({ key: 'j', ctrlKey: true }))).toEqual({ type: 'toggle-bottom' })
    expect(resolveShortcut(key({ key: 'b', metaKey: true }))).toEqual({ type: 'toggle-left' })
  })

  it('maps a bare ? to the help panel', () => {
    expect(resolveShortcut(key({ key: '?' }))).toEqual({ type: 'help' })
  })

  it('never claims mod+s (reserved for save)', () => {
    expect(resolveShortcut(key({ key: 's', metaKey: true }))).toBeNull()
  })

  it('ignores mod+number with extra modifiers', () => {
    expect(resolveShortcut(key({ key: '1', metaKey: true, shiftKey: true }))).toBeNull()
    expect(resolveShortcut(key({ key: '1' }))).toBeNull()
  })
})

describe('command palette shortcut', () => {
  it('maps mod+k to the palette', () => {
    expect(resolveShortcut(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))).toEqual({
      type: 'palette',
    })
    expect(resolveShortcut(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))).toEqual({
      type: 'palette',
    })
  })

  it('leaves plain k alone so it still types', () => {
    expect(resolveShortcut(new KeyboardEvent('keydown', { key: 'k' }))).toBeNull()
  })

  it('does not disturb the existing number bindings', () => {
    expect(resolveShortcut(new KeyboardEvent('keydown', { key: '2', metaKey: true }))).toEqual({
      type: 'view',
      view: 'queue',
    })
  })
})
