// shortcuts.ts — Pure keyboard-shortcut resolution (IDE-style).
//
// Resolving the intent is separate from performing it so the mapping is
// unit-tested without a DOM. useShortcuts owns the listener and the dispatch.
import type { PrimaryView } from './uiStore'

export type ShortcutAction =
  | { type: 'view'; view: PrimaryView }
  | { type: 'close-tab' }
  | { type: 'toggle-bottom' }
  | { type: 'toggle-left' }
  | { type: 'help' }

const NUMBER_VIEW: Record<string, PrimaryView> = {
  '1': 'dashboard',
  '2': 'queue',
  '3': 'runs',
  '4': 'loops',
  '5': 'conduct',
  '6': 'team',
  '7': 'metrics',
}

/** The action a keydown maps to, or null. mod = Cmd (mac) or Ctrl. */
export function resolveShortcut(e: KeyboardEvent): ShortcutAction | null {
  const mod = e.metaKey || e.ctrlKey
  if (mod && !e.shiftKey && !e.altKey) {
    const view = NUMBER_VIEW[e.key]
    if (view) return { type: 'view', view }
    const k = e.key.toLowerCase()
    if (k === 'w') return { type: 'close-tab' }
    if (k === 'j') return { type: 'toggle-bottom' }
    if (k === 'b') return { type: 'toggle-left' }
    // Cmd/Ctrl+S is intentionally left for the editor's own save handler.
  }
  if (!mod && !e.altKey && e.key === '?') return { type: 'help' }
  return null
}
