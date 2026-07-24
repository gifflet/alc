// yamlDoc.ts — Small shared helpers for editing a parsed `yaml` Document while
// preserving comments and unmodeled keys, used by every structured form
// (ManifestForm, BlueprintForm, FlowForm, LoopForm, CheckListEditor).
import type { Document } from 'yaml'

/** Keys of a mapping node (as returned by `doc.get(...)`/`doc.getIn(...)`), or
 * [] when the node is absent or not a map. */
export function mapKeys(node: unknown): string[] {
  const items = (node as { items?: { key: { value?: unknown } }[] } | null)?.items
  return items ? items.map((p) => String(p.key.value ?? p.key)) : []
}

/** Plain strings of a sequence node (as returned by `doc.get(...)`), or []
 * when the node is absent or not a sequence. */
export function seqStrings(node: unknown): string[] {
  const seq = node as { toJSON?: () => unknown } | null
  if (!seq || typeof seq.toJSON !== 'function') return []
  const v = seq.toJSON()
  return Array.isArray(v) ? v.map(String) : []
}

/**
 * Delete a nested path only when it actually exists. `Document#deleteIn`
 * throws when an intermediate map in the path was never set (e.g. deleting
 * `notify.on_task_failed` before `notify:` itself has ever been written) —
 * this guards every such optional-nested-object deletion.
 */
export function safeDeleteIn(doc: Document, path: (string | number)[]): void {
  if (doc.hasIn(path)) doc.deleteIn(path)
}
