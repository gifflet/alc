// commandIndex.ts — What Cmd+K can reach, and in what order.
//
// At ten units in flight, navigation is the bottleneck: reaching one blueprint
// through the tool window costs more than the decision it leads to. The index is
// built from data already in the query cache, so opening the palette costs no
// request.
//
// Matching and ranking are pure functions — the subtle part is the ORDER, and it
// is unit-tested without a DOM (the same split shortcuts.ts uses).

export type CommandKind = 'view' | 'action' | 'blueprint' | 'flow' | 'specialist' | 'loop' | 'primer' | 'prompt' | 'run' | 'task' | 'branch'

export interface Command {
  id: string
  kind: CommandKind
  label: string
  /** Secondary line: what this is, or where it leads. */
  hint?: string
  run: () => void
}

/** Group order in the result list — where an operator expects to look first. */
const KIND_ORDER: CommandKind[] = [
  'view',
  'action',
  'blueprint',
  'flow',
  'specialist',
  'loop',
  'primer',
  'prompt',
  'branch',
  'task',
  'run',
]

type MatchStrength = 'prefix' | 'word' | 'substring' | 'subsequence' | null

/**
 * How well `query` matches `label`, or null.
 *
 * Deliberately not a fuzzy-search dependency: the corpus is tens of items, and a
 * library would be a dependency for a filter. The four tiers are what actually
 * separates "what I typed" from "what happens to contain those letters".
 */
export function matchStrength(label: string, query: string): MatchStrength {
  if (!query) return 'prefix'
  const l = label.toLowerCase()
  const q = query.toLowerCase()
  if (l.startsWith(q)) return 'prefix'
  // A word boundary: "run configurations" should rank for "conf".
  if (new RegExp(`\\b${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`).test(l)) return 'word'
  if (l.includes(q)) return 'substring'

  let i = 0
  for (const ch of l) {
    if (ch === q[i]) i += 1
    if (i === q.length) return 'subsequence'
  }
  return null
}

const STRENGTH_RANK: Record<Exclude<MatchStrength, null>, number> = {
  prefix: 0,
  word: 1,
  substring: 2,
  subsequence: 3,
}

/** Filter and rank commands for `query`. */
export function rankCommands(commands: Command[], query: string): Command[] {
  const scored: Array<{ command: Command; strength: number; kind: number; index: number }> = []
  commands.forEach((command, index) => {
    const strength = matchStrength(command.label, query)
    if (strength === null) return
    scored.push({
      command,
      strength: STRENGTH_RANK[strength],
      kind: KIND_ORDER.indexOf(command.kind),
      index,
    })
  })
  scored.sort(
    (a, b) =>
      // Match quality first: what you typed beats what merely contains it.
      a.strength - b.strength ||
      // Then kind, so views and actions surface above raw data.
      a.kind - b.kind ||
      // Then the order the caller supplied (already recency-sorted for runs).
      a.index - b.index,
  )
  return scored.map((s) => s.command)
}

/** Group ranked results by kind, preserving rank within each group. */
export function groupCommands(commands: Command[]): Array<{ kind: CommandKind; items: Command[] }> {
  const groups = new Map<CommandKind, Command[]>()
  for (const command of commands) {
    const list = groups.get(command.kind) ?? []
    list.push(command)
    groups.set(command.kind, list)
  }
  return KIND_ORDER.filter((k) => groups.has(k)).map((kind) => ({ kind, items: groups.get(kind)! }))
}
