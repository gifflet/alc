// useShortcuts.ts — Bind the global IDE keyboard shortcuts to store actions.
//
// One window-level keydown listener resolves the intent (shortcuts.ts) and runs
// it against the UI store. `?` opens the help panel, but not while typing.
import { useEffect } from 'react'
import { openView } from '../components/ActivityBar'
import { uiStore } from './uiStore'
import { resolveShortcut } from './shortcuts'

/** True when the event target is a text field / editor (so `?` types a char). */
function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable || Boolean(target.closest('.monaco-editor'))
}

function closeActiveTab(): void {
  const { activeTabId, tabs, dirty } = uiStore.getState()
  if (!activeTabId) return
  const tab = tabs.find((t) => t.id === activeTabId)
  // Leave non-closable views and unsaved editors to the explicit close affordance.
  if (!tab?.closable || dirty[activeTabId]) return
  uiStore.closeTab(activeTabId)
}

export function useShortcuts(
  onHelp: () => void,
  onPalette?: () => void,
  onSwitchProject?: () => void,
): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const action = resolveShortcut(e)
      if (!action) return
      if (action.type === 'help' && isEditable(e.target)) return
      e.preventDefault()
      switch (action.type) {
        case 'view':
          openView(action.view)
          break
        case 'close-tab':
          closeActiveTab()
          break
        case 'toggle-bottom':
          uiStore.toggleBottom()
          break
        case 'toggle-left':
          uiStore.toggleLeft()
          break
        case 'help':
          onHelp()
          break
        case 'palette':
          onPalette?.()
          break
        case 'switch-project':
          onSwitchProject?.()
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onHelp, onPalette, onSwitchProject])
}
