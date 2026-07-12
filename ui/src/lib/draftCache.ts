// draftCache.ts — Per-tab editor drafts that survive tab unmount/remount.
//
// TabContent renders only the active tab, so a source editor unmounts when you
// switch away. This module-level cache keeps each tab's draft + baseline so the
// content and the dirty state persist until the tab is actually closed.
export interface DraftEntry {
  draft: string
  baseline: string
}

const cache = new Map<string, DraftEntry>()

export function getDraft(id: string): DraftEntry | undefined {
  return cache.get(id)
}

export function setDraft(id: string, entry: DraftEntry): void {
  cache.set(id, entry)
}

export function clearDraft(id: string): void {
  cache.delete(id)
}

export function clearAllDrafts(): void {
  cache.clear()
}
